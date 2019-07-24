#!/usr/bin/python3

import argparse
import os
import subprocess
import pickle
import re

def parse_args():
    parser = argparse.ArgumentParser(description='Wrapper generator.')
    parser.add_argument('--stubs', type=str, nargs=3, metavar=('header_path', 'functions', 'stub_path'),
            help='parse header for functions and generate (overwrite) function stubs')
    parser.add_argument('--wrapper', type=str, nargs=2, metavar=('wrapper_path', 'stub_path'),
            help='read generated stubs and create (overwrite) wrapper library')
    parser.add_argument('--compiler', type=str, nargs=1, default=['/opt/rocm/bin/hipcc'],
            help='compiler to use for preprocessing header file')
    parser.add_argument('--includes', type=str, nargs=1, default=['-I/opt/rocm/include/'],
            help='include directive to pass to preprocessor')
    return parser.parse_args()

class FunctionInfo:
    def __init__(self, name, text_prototype):
        self.name = name
        arguments_list = name.join(text_prototype.split(name)[1:]).strip('();')
        if '=' in arguments_list:
            # arguments still have default values (int a = 0)
            arguments = []
            for arg in arguments_list.split(','):
                arguments.append(arg.split('=')[0].strip())
            arguments = ', '.join(arguments)
        else:
            arguments = arguments_list

        n_tokens_first_arg = len(arguments.split(',')[0].split())
        if n_tokens_first_arg == 1: # this is a forward declaration. ignore.
            raise ValueError("Invalid function declaration")
        if n_tokens_first_arg > 1:
            self.parameters = ', '.join([p.split()[-1] for p in arguments.split(',')])
        else:
            self.parameters = ''
        self.return_type = text_prototype.split(name)[0].strip()
        self.prototype = self.return_type + ' ' + self.name + '(' + arguments + ')';
        self.pointer = self.return_type + ' (*orig_' + self.name + ')(' + arguments + ')'
        self.cast = self.return_type + ' (*)(' + arguments + ')'

PREPROCESS_CMD = '{compiler} -E {header} {includes}'
FILTER_CMD = ['grep', '-n', '^\(\w\+\**\s\)\{1,\}\w\+\s*(']

def get_prototypes(header_file, functions, compiler, includes):
    preprocess = subprocess.Popen(
            PREPROCESS_CMD.format(compiler=compiler, header=header_file, includes=includes).split(),
            stdout=subprocess.PIPE)
    filtered = subprocess.check_output(FILTER_CMD, stdin=preprocess.stdout).splitlines()
    preprocess.wait()
   
    preprocessed = subprocess.check_output(
            PREPROCESS_CMD.format(compiler=compiler, header=header_file, includes=includes).
            split()).splitlines()

    functionInfos = []
    currentFunction = ''
    currentParse = ''
    for declaration in filtered:
        declaration = declaration.decode('utf-8')
        if not currentFunction:
            for function in functions:
                if not re.search('\s' + function + '\s*\(', declaration): continue
                if re.search('(static|inline)', declaration): continue
                currentFunction = function
                functions.remove(function)
                line = int(declaration.split(':')[0])
                break
        if not currentFunction: continue
        while not re.search('[;{]', currentParse):
            currentParse += preprocessed[line - 1].decode('utf-8')
            line += 1
        if '{' in currentParse: # parsed a definition, not declaration.
            # chop off everything after and including the {
            currentParse = currentParse[:currentParse.index('{')]
            currentParse = currentParse.strip()
            currentParse += ';'
        currentParse = currentParse.strip()
        try:
            functionInfos.append(FunctionInfo(currentFunction, currentParse))
        except ValueError:
            functions.add(currentFunction)
        currentParse = ''
        currentFunction = ''
    return functionInfos 

class HeaderInfo:
    def __init__(self, header_file, functions, compiler, includes):
        self.header_file = header_file
        self.functions = get_prototypes(header_file, functions, compiler, includes)

FUNC_BODY = """\t// {header_file} wrapper - stub body for {func_name}
\t{func_ret} ret;
\t// Write your own code here
\tret = orig_{func_name}({func_parms});
\treturn ret;"""

STUB_FILE_EXTENSION = '.cpp'
PICKLE_FILE_EXTENSION = '.pickle'
STUB_INCLUDES = 'includes.txt'

def generate_stubs(location, header):
    os.makedirs(location, exist_ok=True)
    for function in header.functions:
        with open(location + '/' + function.name + STUB_FILE_EXTENSION, 'w') as stub:
            stub.write(FUNC_BODY.format(
                header_file = header.header_file, func_name = function.name,
                func_ret = function.return_type, func_parms = function.parameters))
        with open(location + '/' + function.name + PICKLE_FILE_EXTENSION, 'wb') as pick:
            pickle.dump(function, pick)
    with open(location + '/' + STUB_INCLUDES, 'a') as inc:
        inc.write('#include "' + header.header_file + '"\n')

def check_missing_stubs(location, functions):
    stubs = os.listdir(location)
    allStubsFound = True 
    for function in functions:
        if not function + STUB_FILE_EXTENSION in stubs:
            if allStubsFound:
                print("Functions missing stub files: ")
            print(function + ", ", end='')
            allStubsFound = False
    if allStubsFound:
        print("All stubs generated.")
    else:
        print("\nPerhaps functions are defined in multiple headers."
                " Generate more stubs using different headers to complete the stub set.")

def functionsSet(functions_path):
    # build set of all functions we want to find
    functions = set()
    with open(functions_path, 'r') as fns:
        for fn in fns:
            functions.add(fn.strip())
    return functions

# library header
LIB_HEADER = """\
#include <stdio.h>
#include <dlfcn.h>
#include <unistd.h>
{includes}
"""

# Intercept function template
FUNC_TEMPLATE = """
static {func_ptr} = NULL;
{func_proto} {{
  {custom_code}
}}
"""

# Library init function header

INIT_HEADER = """
__attribute__((constructor)) static void init() {
\t// clear dlerror
\tdlerror();
"""

# Init template for each function to intercept

INIT_TEMPLATE = """\
\tif (!(orig_{func_name} = ({func_cast}) dlsym(RTLD_NEXT, "{func_name}")))
\t\tfprintf(stderr, "Error looking up {func_name}: %s\\n", dlerror());
"""

# End init function

INIT_FOOTER = """}"""

def generate_wrapper(wrapper_path, stubs_path):
    with open(wrapper_path, 'w') as wrapper:
        try:
            with open(stubs_path + '/' + STUB_INCLUDES, 'r') as inc:
                wrapper.write(LIB_HEADER.format(includes = inc.read()))
        except FileNotFoundError:
            print("Stub generation incomplete. Please regenerate stubs before generating wrapper.")
            exit(-1)
        stubs = os.listdir(stubs_path)
        function_initialization = ''
        for stub in stubs:
            if not STUB_FILE_EXTENSION in stub: continue
            with open(stubs_path + '/' + stub, 'r') as s, open(stubs_path + '/' +
                    stub.split(STUB_FILE_EXTENSION)[0] + PICKLE_FILE_EXTENSION, 'rb') as p:
                function = pickle.load(p)
                wrapper.write(FUNC_TEMPLATE.format(func_ptr=function.pointer,
                    func_proto = function.prototype, custom_code=s.read()))
                function_initialization += INIT_TEMPLATE.format(func_name=function.name,
                        func_cast=function.cast);
        wrapper.write(INIT_HEADER)
        wrapper.write(function_initialization)
        wrapper.write(INIT_FOOTER)

if __name__ == '__main__':
    args = parse_args()
    if args.stubs is not None:
        header = HeaderInfo(args.stubs[0], functionsSet(args.stubs[1]), args.compiler[0],
                args.includes[0])
        generate_stubs(args.stubs[2], header)
        check_missing_stubs(args.stubs[2], functionsSet(args.stubs[1]))
    if args.wrapper is not None:
        generate_wrapper(args.wrapper[0], args.wrapper[1])

