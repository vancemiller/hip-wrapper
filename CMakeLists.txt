cmake_minimum_required(VERSION 3.5)
project(hip_wrapper LANGUAGES CXX)

set (HIP_HEADER /opt/rocm/hip/include/hip/hip_runtime.h)
set (PREPROCESSOR /opt/rocm/bin/hipcc)
set (PREPROCESSOR_INCLUDES \\\\-I/opt/rocm/include)
set (HIP_DIR /opt/rocm/hip/lib/cmake/hip)
set (hcc_DIR /opt/rocm/hcc/lib/cmake/hcc)
find_package(HIP REQUIRED)

add_custom_command(OUTPUT stubs COMMAND ${CMAKE_SOURCE_DIR}/wrap.py 
	ARGS --stubs ${HIP_HEADER} ${CMAKE_SOURCE_DIR}/hip-functions.txt stubs 
	--compiler ${PREPROCESSOR} --includes "${PREPROCESSOR_INCLUDES}"
	COMMENT "Generating stubs")
add_custom_command(OUTPUT ${PROJECT_NAME}.cpp
	COMMAND ${CMAKE_SOURCE_DIR}/wrap.py ARGS --wrapper ${PROJECT_NAME}.cpp stubs
	DEPENDS stubs ${CMAKE_SOURCE_DIR}/wrap.py COMMENT "Generating library source")
add_library(${PROJECT_NAME} SHARED ${CMAKE_BINARY_DIR}/${PROJECT_NAME}.cpp)
target_link_libraries(${PROJECT_NAME} ${HIP_LIBRARIES})
