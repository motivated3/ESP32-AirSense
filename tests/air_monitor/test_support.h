#pragma once
#include <cmath>
#include <cstdio>
#include <cstdlib>

#define CHECK(condition)                                                         \
    do {                                                                         \
        if (!(condition)) {                                                      \
            std::fprintf(stderr, "%s:%d: %s\n", __FILE__, __LINE__, #condition); \
            std::exit(1);                                                        \
        }                                                                        \
    } while (0)
#define NEAR(a, b, epsilon) CHECK(std::fabs((a) - (b)) < (epsilon))
