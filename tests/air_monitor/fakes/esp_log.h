#pragma once
#include <cstdlib>
#define ESP_LOGW(...) ((void)0)
#define ESP_LOGE(...) ((void)0)
#define ESP_ERROR_CHECK(error) \
    do {                       \
        if ((error) != 0)      \
            std::abort();      \
    } while (0)
