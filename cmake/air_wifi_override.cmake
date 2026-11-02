# Keep the pinned vendor component intact. Only AIR uses the generated event bridge.
idf_component_get_property(AIR_WIFI_DIR "78__esp-wifi-connect" COMPONENT_DIR)
idf_component_get_property(AIR_WIFI_LIB "78__esp-wifi-connect" COMPONENT_LIB)
set(AIR_WIFI_SOURCE "${AIR_WIFI_DIR}/wifi_manager.cc")
set(AIR_WIFI_OVERRIDE "${CMAKE_BINARY_DIR}/generated/air_wifi/wifi_manager.cc")
set(AIR_WIFI_GENERATOR "${PROJECT_DIR}/scripts/generate_air_wifi_override.py")
set(AIR_WIFI_INCLUDE "${PROJECT_DIR}/main/boards/custom/waveshare-air-monitor-1.8-v1")
execute_process(
    COMMAND "${PYTHON}" "${AIR_WIFI_GENERATOR}" --source "${AIR_WIFI_SOURCE}" --output "${AIR_WIFI_OVERRIDE}"
    RESULT_VARIABLE AIR_WIFI_RESULT
    ERROR_VARIABLE AIR_WIFI_ERROR
)
if(NOT AIR_WIFI_RESULT EQUAL 0)
    message(FATAL_ERROR "AIR WiFi override generation failed: ${AIR_WIFI_ERROR}")
endif()
set_property(DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
    "${AIR_WIFI_SOURCE}" "${AIR_WIFI_GENERATOR}")
get_target_property(AIR_WIFI_SOURCES "${AIR_WIFI_LIB}" SOURCES)
set(AIR_WIFI_COUNT 0)
set(AIR_WIFI_RETAINED)
foreach(source IN LISTS AIR_WIFI_SOURCES)
    if(source STREQUAL AIR_WIFI_SOURCE)
        math(EXPR AIR_WIFI_COUNT "${AIR_WIFI_COUNT} + 1")
    else()
        list(APPEND AIR_WIFI_RETAINED "${source}")
    endif()
endforeach()
if(NOT AIR_WIFI_COUNT EQUAL 1)
    message(FATAL_ERROR "Expected one pinned WiFi manager source, found ${AIR_WIFI_COUNT}")
endif()
set_property(TARGET "${AIR_WIFI_LIB}" PROPERTY SOURCES "${AIR_WIFI_RETAINED}")
target_sources("${AIR_WIFI_LIB}" PRIVATE "${AIR_WIFI_OVERRIDE}")
target_include_directories("${AIR_WIFI_LIB}" PRIVATE "${AIR_WIFI_INCLUDE}")
file(SHA256 "${AIR_WIFI_SOURCE}" AIR_WIFI_VENDOR_SHA)
file(SHA256 "${AIR_WIFI_OVERRIDE}" AIR_WIFI_GENERATED_SHA)
file(SHA256 "${AIR_WIFI_GENERATOR}" AIR_WIFI_GENERATOR_SHA)
file(WRITE "${CMAKE_BINARY_DIR}/generated/air_wifi/manifest.json"
    "{\n  \"vendor_sha256\": \"${AIR_WIFI_VENDOR_SHA}\",\n  \"generated_sha256\": \"${AIR_WIFI_GENERATED_SHA}\",\n  \"generator_sha256\": \"${AIR_WIFI_GENERATOR_SHA}\"\n}\n")
