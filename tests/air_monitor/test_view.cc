#include <material_symbols.h>
#include <cfenv>
#include <cstring>
#include <limits>
#include <string>
#include <vector>
#include "air_fonts.h"
#include "air_model.h"
#include "air_view.h"
#include "test_support.h"
using namespace air;
LV_FONT_DECLARE(font_material_symbols_20_4);
static lv_obj_t* Find(lv_obj_t* root, const char* text) {
    if (lv_obj_check_type(root, &lv_label_class) && std::strcmp(lv_label_get_text(root), text) == 0)
        return root;
    for (uint32_t i = 0; i < lv_obj_get_child_count(root); ++i) {
        if (auto* found = Find(lv_obj_get_child(root, i), text))
            return found;
    }
    return nullptr;
}
static void Click(lv_obj_t* root, const char* text) {
    auto* label = Find(root, text);
    CHECK(label);
    lv_obj_send_event(lv_obj_get_parent(label), LV_EVENT_CLICKED, nullptr);
}
static void CheckNoticeContrast(lv_obj_t* notice) {
    CHECK(notice);
    CHECK(!lv_color_eq(lv_obj_get_style_text_color(notice, LV_PART_MAIN),
                       lv_obj_get_style_bg_color(lv_obj_get_parent(notice), LV_PART_MAIN)));
}
static void CheckGlyphs(lv_obj_t* root) {
    if (lv_obj_check_type(root, &lv_label_class)) {
        const auto* font = lv_obj_get_style_text_font(root, LV_PART_MAIN);
        const auto* p = reinterpret_cast<const unsigned char*>(lv_label_get_text(root));
        while (*p) {
            uint32_t code = *p++;
            if (code >= 0xC0) {
                const int extra = code < 0xE0 ? 1 : code < 0xF0 ? 2 : 3;
                code &= extra == 1 ? 0x1F : extra == 2 ? 0x0F : 7;
                for (int i = 0; i < extra; ++i)
                    code = (code << 6) | (*p++ & 0x3F);
            }
            if (code < 32)
                continue;
            lv_font_glyph_dsc_t glyph{};
            if (!lv_font_get_glyph_dsc(font, &glyph, code, 0) || glyph.is_placeholder) {
                std::fprintf(stderr, "missing glyph U+%04X in %s\n", code, lv_label_get_text(root));
                CHECK(false);
            }
        }
    }
    for (uint32_t i = 0; i < lv_obj_get_child_count(root); ++i)
        CheckGlyphs(lv_obj_get_child(root, i));
}
static void Render(lv_display_t* display, const std::vector<uint32_t>& pixels,
                   const char* directory, const char* name) {
    if (!directory)
        return;
    lv_obj_invalidate(lv_display_get_screen_active(display));
    lv_refr_now(display);
    const std::string path = std::string(directory) + "/" + name + ".ppm";
    auto* file = std::fopen(path.c_str(), "wb");
    CHECK(file);
    std::fprintf(file, "P6\n368 448\n255\n");
    for (auto pixel : pixels) {
        const uint8_t rgb[] = {static_cast<uint8_t>(pixel >> 16), static_cast<uint8_t>(pixel >> 8),
                               static_cast<uint8_t>(pixel)};
        std::fwrite(rgb, 1, 3, file);
    }
    std::fclose(file);
}
static void CheckRect(lv_obj_t* object, int x, int y, int width, int height) {
    CHECK(object);
    CHECK(lv_obj_get_x(object) == x && lv_obj_get_y(object) == y);
    CHECK(lv_obj_get_width(object) == width && lv_obj_get_height(object) == height);
}
static lv_area_t TextBounds(lv_obj_t* label) {
    CHECK(label);
    lv_point_t size;
    lv_text_get_size(
        &size, lv_label_get_text(label), lv_obj_get_style_text_font(label, LV_PART_MAIN),
        lv_obj_get_style_text_letter_space(label, LV_PART_MAIN),
        lv_obj_get_style_text_line_space(label, LV_PART_MAIN), LV_COORD_MAX, LV_TEXT_FLAG_NONE);
    CHECK(size.x <= lv_obj_get_width(label) && size.y <= lv_obj_get_height(label));
    lv_area_t area;
    lv_obj_get_coords(label, &area);
    const auto align = lv_obj_get_style_text_align(label, LV_PART_MAIN);
    if (align == LV_TEXT_ALIGN_RIGHT)
        area.x1 += lv_obj_get_width(label) - size.x;
    else if (align == LV_TEXT_ALIGN_CENTER)
        area.x1 += (lv_obj_get_width(label) - size.x) / 2;
    area.x2 = area.x1 + size.x - 1;
    area.y2 = area.y1 + size.y - 1;
    return area;
}
static void CheckSeparate(lv_obj_t* first, lv_obj_t* second) {
    const auto a = TextBounds(first), b = TextBounds(second);
    CHECK(a.x2 < b.x1 || b.x2 < a.x1 || a.y2 < b.y1 || b.y2 < a.y1);
}
static lv_area_t InkBounds(lv_obj_t* label, const std::vector<uint32_t>& pixels) {
    lv_area_t roi;
    lv_obj_get_coords(label, &roi);
    const auto foreground =
        lv_color_to_u32(lv_obj_get_style_text_color(label, LV_PART_MAIN)) & 0xFFFFFF;
    lv_area_t ink{368, 448, -1, -1};
    for (int y = std::max(0, static_cast<int>(roi.y1));
         y <= std::min(447, static_cast<int>(roi.y2)); ++y) {
        for (int x = std::max(0, static_cast<int>(roi.x1));
             x <= std::min(367, static_cast<int>(roi.x2)); ++x) {
            if ((pixels[y * 368 + x] & 0xFFFFFF) != foreground)
                continue;
            ink.x1 = std::min(ink.x1, x);
            ink.x2 = std::max(ink.x2, x);
            ink.y1 = std::min(ink.y1, y);
            ink.y2 = std::max(ink.y2, y);
        }
    }
    if (ink.x1 > ink.x2 || ink.y1 > ink.y2)
        std::fprintf(stderr, "no foreground pixels for '%s' (#%06X)\n", lv_label_get_text(label),
                     static_cast<unsigned>(foreground));
    CHECK(ink.x1 <= ink.x2 && ink.y1 <= ink.y2);
    return ink;
}
static void CheckClockHeader(lv_obj_t* page, bool home, const char* clock_text, bool connected) {
    auto* clock = Find(page, clock_text);
    auto* wifi = Find(page, connected ? MATERIAL_SYMBOLS_WIFI : MATERIAL_SYMBOLS_WIFI_OFF);
    CHECK(clock && wifi);
    CHECK(!Find(page, connected ? MATERIAL_SYMBOLS_WIFI_OFF : MATERIAL_SYMBOLS_WIFI));
    CHECK(lv_obj_get_style_text_font(clock, LV_PART_MAIN) ==
          (home ? &font_air_text_20 : &font_air_text_18));
    CHECK(lv_obj_get_style_text_font(wifi, LV_PART_MAIN) == &font_material_symbols_20_4);
    CHECK(lv_obj_get_parent(wifi) == page);
    CHECK(!lv_obj_has_flag(wifi, LV_OBJ_FLAG_CLICKABLE));
    CHECK(lv_obj_get_style_bg_opa(wifi, LV_PART_MAIN) == LV_OPA_TRANSP);
    CheckSeparate(clock, wifi);
    if (home) {
        CheckRect(clock, 24, 24, 124, 26);
        CheckRect(wifi, 322, 24, 22, 22);
        CHECK(!Find(page, "舱内空气"));
        auto* status = Find(page, "实时监测");
        CHECK(status);
        auto* pill = lv_obj_get_parent(status);
        CheckRect(pill, 160, 20, 136, 30);
        CHECK(lv_obj_get_x(clock) + lv_obj_get_width(clock) <= lv_obj_get_x(pill));
        CHECK(lv_obj_get_x(pill) + lv_obj_get_width(pill) <= lv_obj_get_x(wifi));
        TextBounds(status);
    } else {
        auto* title = Find(page, "历史曲线");
        if (!title)
            title = Find(page, "设置");
        auto* back = Find(page, MATERIAL_SYMBOLS_ARROW_BACK);
        CHECK(title && back);
        CHECK(lv_obj_get_parent(lv_obj_get_parent(back)) == page);
        CHECK(lv_obj_has_flag(lv_obj_get_parent(back), LV_OBJ_FLAG_CLICKABLE));
        CheckSeparate(title, clock);
        CheckSeparate(back, title);
        CHECK(lv_obj_get_y(clock) < 60 && lv_obj_get_x(clock) > lv_obj_get_x(title));
        CHECK(lv_obj_get_y(wifi) < 60);
    }
}
static void CheckClockTransitions(AirView& view, AirUiState& state, const AirSnapshot& snapshot,
                                  const PowerSnapshot& power, std::time_t& wall_time,
                                  lv_obj_t* screen, lv_display_t* display, size_t& flushes,
                                  const std::vector<uint32_t>& pixels, const char* directory) {
    const auto saved_time = wall_time;
    const auto saved_page = state.page();
    const bool saved_night = state.night();
    auto* home = lv_obj_get_parent(Find(screen, "CO₂"));
    auto* trend = lv_obj_get_parent(Find(screen, "历史曲线"));
    auto* settings = lv_obj_get_parent(Find(screen, "设置"));
    lv_obj_t* pages[] = {home, trend, settings};
    // A new voice session opens chat; return explicitly before checking the air headers.
    view.Refresh(snapshot, power, kDeviceStateListening, true, true, "Wi-Fi 已连接");
    view.WakeHome();
    auto refresh = [&](bool connected) {
        // Connection text and cloud activity cannot override the acquired-IP bit.
        view.Refresh(snapshot, power, kDeviceStateListening, connected, true,
                     connected ? "Wi-Fi 离线" : "Wi-Fi 已连接");
        lv_obj_update_layout(screen);
    };
    for (bool night : {false, true}) {
        state.SetTheme(night);
        for (int i = 0; i < 3; ++i) {
            view.Navigate(static_cast<Page>(i), false);
            wall_time = saved_time;
            refresh(true);
            CheckClockHeader(pages[i], i == 0, "10-23 14:36", true);
            lv_refr_now(display);
            flushes = 0;
            wall_time += 59;
            refresh(true);
            lv_refr_now(display);
            CHECK(flushes == 0);  // Seconds do not dirty the minute-only clock.
            ++wall_time;
            flushes = 0;
            refresh(true);
            CheckClockHeader(pages[i], i == 0, "10-23 14:37", true);
            lv_refr_now(display);
            CHECK(flushes > 0);
            refresh(false);
            CheckClockHeader(pages[i], i == 0, "10-23 14:37", false);
            if (i == 0 && !night)
                Render(display, pixels, directory, "home-offline");
            wall_time += 60;
            refresh(false);
            CheckClockHeader(pages[i], i == 0, "10-23 14:38", false);
            wall_time = 0;
            refresh(false);
            CheckClockHeader(pages[i], i == 0, "--:--", false);
            if (i == 0 && !night)
                Render(display, pixels, directory, "home-uncalibrated");
            refresh(true);
            CheckClockHeader(pages[i], i == 0, "--:--", true);
            lv_refr_now(display);
            flushes = 0;
            refresh(true);
            lv_refr_now(display);
            CHECK(flushes == 0);
            wall_time = saved_time;
            refresh(true);
            CheckClockHeader(pages[i], i == 0, "10-23 14:36", true);
        }
    }
    state.SetTheme(saved_night);
    view.Navigate(saved_page, false);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
}
static void CheckHchoLayout(lv_obj_t* home, lv_obj_t* number, lv_obj_t* status,
                            lv_display_t* display, const std::vector<uint32_t>& pixels) {
    lv_obj_update_layout(home);
    CHECK(!Find(home, "温度") && !Find(home, "湿度"));
    CHECK(Find(home, MATERIAL_SYMBOLS_DEVICE_THERMOSTAT));
    auto* card = lv_obj_get_parent(number);
    CheckRect(card, 16, 260, 336, 94);
    CHECK(lv_obj_get_style_text_font(number, LV_PART_MAIN) == &font_air_digits_64);
    auto* title = Find(card, "甲醛");
    auto* unit = Find(card, "ppb");
    CHECK(title && unit);
    for (uint32_t i = 0; i < lv_obj_get_child_count(card); ++i) {
        auto* label = lv_obj_get_child(card, i);
        if (!lv_obj_check_type(label, &lv_label_class))
            continue;
        const auto text = TextBounds(label);
        lv_area_t bounds;
        lv_obj_get_coords(card, &bounds);
        CHECK(text.x1 >= bounds.x1 && text.y1 >= bounds.y1);
        CHECK(text.x2 <= bounds.x2 && text.y2 <= bounds.y2);
        if (label != number)
            CheckSeparate(number, label);
    }
    lv_refr_now(display);
    const auto number_ink = InkBounds(number, pixels);
    const auto title_ink = InkBounds(title, pixels);
    const auto status_ink = InkBounds(status, pixels);
    lv_area_t card_bounds, number_bounds, unit_bounds;
    lv_obj_get_coords(card, &card_bounds);
    lv_obj_get_coords(number, &number_bounds);
    lv_obj_get_coords(unit, &unit_bounds);
    const double card_center = (card_bounds.y1 + card_bounds.y2) / 2.0;
    const double number_center = (number_ink.y1 + number_ink.y2) / 2.0;
    const double left_center = (title_ink.y1 + status_ink.y2) / 2.0;
    const int left_gap = status_ink.y1 - title_ink.y2 - 1;
    const auto* number_font = lv_obj_get_style_text_font(number, LV_PART_MAIN);
    const auto* unit_font = lv_obj_get_style_text_font(unit, LV_PART_MAIN);
    const int number_baseline =
        number_bounds.y1 + number_font->line_height - number_font->base_line;
    const int unit_baseline = unit_bounds.y1 + unit_font->line_height - unit_font->base_line;
    std::printf(
        "HCHO ink '%s'/'%s': card center=%.1f number center=%.1f left center=%.1f "
        "gap=%d baselines=%d/%d\n",
        lv_label_get_text(number), lv_label_get_text(status), card_center, number_center,
        left_center, left_gap, number_baseline, unit_baseline);
    CHECK(std::abs(number_center - card_center) <= 1.0);
    CHECK(std::abs(left_center - card_center) <= 2.0);
    CHECK(left_gap >= 6 && left_gap <= 12);
    CHECK(number_baseline == unit_baseline);
    auto* temperature = Find(home, "25.4°C");
    auto* humidity = Find(home, "46%");
    CHECK(temperature && humidity);
    CHECK(lv_obj_get_y(temperature) >= 354 && lv_obj_get_y(humidity) >= 354);
    CHECK(lv_obj_get_y(temperature) + lv_obj_get_height(temperature) <= lv_obj_get_height(home));
    CHECK(lv_obj_get_y(humidity) + lv_obj_get_height(humidity) <= lv_obj_get_height(home));
    CheckSeparate(temperature, humidity);
    lv_area_t page_bounds;
    lv_obj_get_coords(home, &page_bounds);
    auto* thermostat = Find(home, MATERIAL_SYMBOLS_DEVICE_THERMOSTAT);
    const auto thermostat_bounds = TextBounds(thermostat);
    CHECK(thermostat_bounds.x1 >= page_bounds.x1 && thermostat_bounds.y1 >= page_bounds.y1);
    CHECK(thermostat_bounds.x2 <= page_bounds.x2);
    lv_obj_t* drop = nullptr;
    for (uint32_t i = 0; i < lv_obj_get_child_count(home); ++i) {
        auto* child = lv_obj_get_child(home, i);
        if (lv_obj_check_type(child, &lv_line_class)) {
            CHECK(!drop);
            drop = child;
        }
    }
    CHECK(drop && lv_line_get_point_count(drop) > 0);
    const auto* points = lv_line_get_points(drop);
    auto max_y = points[0].y;
    for (uint32_t i = 1; i < lv_line_get_point_count(drop); ++i)
        max_y = std::max(max_y, points[i].y);
    lv_area_t drop_bounds;
    lv_obj_get_coords(drop, &drop_bounds);
    const auto drop_bottom =
        drop_bounds.y1 + max_y + lv_obj_get_style_line_width(drop, LV_PART_MAIN) / 2;
    if (thermostat_bounds.y2 > page_bounds.y2 || drop_bottom > page_bounds.y2)
        std::fprintf(stderr, "home bottom=%d thermostat bottom=%d drop bottom=%.0f\n",
                     static_cast<int>(page_bounds.y2), static_cast<int>(thermostat_bounds.y2),
                     static_cast<double>(drop_bottom));
    CHECK(thermostat_bounds.y2 <= page_bounds.y2 && drop_bottom <= page_bounds.y2);
    auto* footer = Find(lv_obj_get_parent(home), "语音");
    CHECK(footer);
    CheckSeparate(temperature, footer);
    CheckSeparate(humidity, footer);
    CheckSeparate(thermostat, footer);
}
static void CheckHchoStates(AirView& view, AirUiState& state, AirSnapshot& snapshot,
                            const PowerSnapshot& power, lv_obj_t* home, lv_obj_t* number,
                            lv_display_t* display, const std::vector<uint32_t>& pixels,
                            const char* directory) {
    const auto saved = snapshot;
    const bool saved_night = state.night();
    for (bool night : {false, true}) {
        state.SetTheme(night);
        for (int scenario = 0; scenario < 7; ++scenario) {
            snapshot = saved;
            snapshot.sfa.ppb = 2000;
            const char* status = "HCHO";
            const char* value = "2000";
            const char* preview = "home-four-digit-hcho";
            switch (scenario) {
                case 1:
                    snapshot.hcho.connected = snapshot.hcho.has_value = false;
                    snapshot.hcho.within_spec = false;
                    status = "等待采样";
                    value = "—";
                    preview = "home-hcho-waiting";
                    break;
                case 2:
                    snapshot.hcho.ready = false;
                    status = "预热中";
                    preview = "home-hcho-warming";
                    break;
                case 3:
                    snapshot.hcho.errors = 3;
                    status = "读取异常";
                    preview = "home-hcho-error";
                    break;
                case 4:
                    snapshot.hcho.environment_ok = snapshot.hcho.within_spec = false;
                    status = "超出额定条件";
                    preview = "home-hcho-outside-spec";
                    break;
                case 5:
                    snapshot.sfa.ppb = std::numeric_limits<float>::quiet_NaN();
                    value = "—";
                    preview = "home-hcho-invalid";
                    break;
                case 6:
                    snapshot.sfa.ppb = 18;
                    value = "18";
                    preview = "home-hcho-normal";
                    break;
            }
            view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
            CHECK(std::strcmp(lv_label_get_text(number), value) == 0);
            auto* status_label = Find(lv_obj_get_parent(number), status);
            CHECK(status_label);
            CheckHchoLayout(home, number, status_label, display, pixels);
            CheckGlyphs(home);
            const std::string name = std::string(preview) + (night ? "-night" : "-day");
            Render(display, pixels, directory, name.c_str());
        }
    }
    snapshot = saved;
    state.SetTheme(saved_night);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
}
static void CheckColor(lv_obj_t* label, uint32_t color) {
    if (!lv_color_eq(lv_obj_get_style_text_color(label, LV_PART_MAIN), lv_color_hex(color)))
        std::fprintf(stderr, "reading %s: expected #%06X, got #%06X\n", lv_label_get_text(label),
                     color,
                     lv_color_to_u32(lv_obj_get_style_text_color(label, LV_PART_MAIN)) & 0xFFFFFF);
    CHECK(lv_color_eq(lv_obj_get_style_text_color(label, LV_PART_MAIN), lv_color_hex(color)));
}
static void CheckLargeTextContrast(lv_obj_t* label, lv_color_t background) {
    auto luminance = [](lv_color_t color) {
        auto linear = [](uint8_t value) {
            const double c = value / 255.0;
            return c <= 0.04045 ? c / 12.92 : std::pow((c + 0.055) / 1.055, 2.4);
        };
        return 0.2126 * linear(color.red) + 0.7152 * linear(color.green) +
               0.0722 * linear(color.blue);
    };
    const double a = luminance(lv_obj_get_style_text_color(label, LV_PART_MAIN));
    const double b = luminance(background);
    CHECK((std::max(a, b) + 0.05) / (std::min(a, b) + 0.05) >= 3.0);
}
static void CheckReadingColors(AirView& view, AirUiState& state, AirSnapshot& snapshot,
                               const PowerSnapshot& power, const AlertSnapshot& saved_alert,
                               lv_obj_t* screen, lv_obj_t* co2_number, lv_obj_t* hcho_number,
                               lv_display_t* display, const std::vector<uint32_t>& pixels,
                               const char* directory) {
    const auto saved_state = state;
    const auto saved_snapshot = snapshot;
    auto* trend_page = lv_obj_get_parent(Find(screen, "历史曲线"));
    lv_obj_update_layout(screen);
    lv_obj_t* trend_number = nullptr;
    for (uint32_t i = 0; i < lv_obj_get_child_count(trend_page); ++i) {
        auto* child = lv_obj_get_child(trend_page, i);
        if (lv_obj_check_type(child, &lv_label_class) && lv_obj_get_y(child) == 166)
            trend_number = child;
    }
    CHECK(trend_number);
    state.reduce_motion = true;
    state.SetTheme(false);
    view.SetAlerts({}, snapshot, power);
    view.Navigate(Page::Home, false);
    auto refresh = [&]() {
        view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    };
    auto valid = snapshot;
    for (auto* channel : {&valid.co2, &valid.hcho}) {
        channel->has_value = channel->has_frame = channel->connected = channel->ready = true;
        channel->within_spec = channel->environment_ok = true;
        channel->stale = false;
        channel->errors = 0;
    }
    valid.sfa.ready = valid.sfa.within_spec = true;
    valid.sfa.status = 0;
    // Boundary colors follow the displayed integer; returning below a boundary restores normal.
    struct Case {
        uint16_t co2;
        float hcho;
        uint32_t co2_color, hcho_color, hcho_trend_color;
        const char* hcho_text;
        const char* render;
    };
    const Case cases[] = {
        {999, 64.49f, 0x153D32, 0xF1FAEE, 0x153D32, "64", "colors-normal-day"},
        {1000, 64.5f, 0x936200, 0xFFDA75, 0x936200, "65", "colors-yellow-day"},
        {1999, 79.49f, 0x936200, 0xFFDA75, 0x936200, "79", nullptr},
        {2000, 79.5f, 0xBB3038, 0xFFBFC5, 0xBB3038, "80", "colors-red-day"},
        {65535, 1500, 0xBB3038, 0xFFBFC5, 0xBB3038, "1500", nullptr},
        {864, 18, 0x153D32, 0xF1FAEE, 0x153D32, "18", nullptr},
    };
    for (const auto& test : cases) {
        snapshot = valid;
        snapshot.scd.ppm = test.co2;
        snapshot.sfa.ppb = test.hcho;
        snapshot.co2.within_spec = test.co2 <= 5000;
        refresh();
        CheckColor(co2_number, test.co2_color);
        CheckColor(hcho_number, test.hcho_color);
        CHECK(std::strcmp(lv_label_get_text(hcho_number), test.hcho_text) == 0);
        CheckLargeTextContrast(co2_number, lv_color_hex(0xEEF5EC));
        auto* card = lv_obj_get_parent(hcho_number);
        CheckLargeTextContrast(hcho_number, lv_obj_get_style_bg_color(card, LV_PART_MAIN));
        CheckLargeTextContrast(hcho_number, lv_obj_get_style_bg_grad_color(card, LV_PART_MAIN));
        if (test.render)
            Render(display, pixels, directory, test.render);
        view.Navigate(Page::Trend, false);
        Click(screen, "CO₂");
        CheckColor(trend_number, test.co2_color);
        Click(screen, "甲醛 HCHO");
        CheckColor(trend_number, test.hcho_trend_color);
        CHECK(std::strcmp(lv_label_get_text(trend_number), test.hcho_text) == 0);
        view.Navigate(Page::Home, false);
    }
    // Theme changes and samples received while a page is hidden cannot leave stale colors.
    view.Navigate(Page::Settings, false);
    snapshot.scd.ppm = 2400;
    snapshot.sfa.ppb = 90;
    refresh();
    view.Navigate(Page::Home, false);
    CheckColor(co2_number, 0xBB3038);
    CheckColor(hcho_number, 0xFFBFC5);
    state.SetTheme(true);
    view.ApplyTheme();
    CheckColor(co2_number, 0xFFBFC5);
    CheckColor(hcho_number, 0xFFBFC5);
    CheckLargeTextContrast(co2_number, lv_color_hex(0x08150F));
    Render(display, pixels, directory, "colors-red-night");
    view.Navigate(Page::Trend, false);
    CheckColor(trend_number, 0xFFBFC5);
    snapshot.scd.ppm = 1200;
    snapshot.sfa.ppb = 70;
    refresh();
    CheckColor(trend_number, 0xFFDA75);
    Click(screen, "CO₂");
    CheckColor(trend_number, 0xFFDA75);
    state.SetTheme(false);
    view.ApplyTheme();
    CheckColor(trend_number, 0x936200);
    view.Navigate(Page::Home, false);
    CheckColor(co2_number, 0x936200);
    CheckColor(hcho_number, 0xFFDA75);
    // Every invalid channel state is neutral, even when the last retained reading is high.
    for (int reason = 0; reason < 8; ++reason) {
        snapshot = valid;
        snapshot.scd.ppm = 2400;
        snapshot.sfa.ppb = 90;
        for (auto* channel : {&snapshot.co2, &snapshot.hcho}) {
            switch (reason) {
                case 0:
                    channel->has_value = false;
                    break;
                case 1:
                    channel->connected = false;
                    break;
                case 2:
                    channel->ready = false;
                    break;
                case 3:
                    channel->stale = true;
                    break;
                case 4:
                    channel->errors = 1;
                    break;
                case 5:
                    channel->errors = 3;
                    break;
                case 6:
                    channel->environment_ok = false;
                    break;
                case 7:
                    channel->within_spec = false;
                    break;
            }
        }
        refresh();
        CheckColor(co2_number, 0x658475);
        CheckColor(hcho_number, 0xADBEAF);
        view.Navigate(Page::Trend, false);
        Click(screen, "CO₂");
        CheckColor(trend_number, 0x658475);
        Click(screen, "甲醛 HCHO");
        CheckColor(trend_number, 0x658475);
        view.Navigate(Page::Home, false);
    }
    for (float invalid : {std::numeric_limits<float>::quiet_NaN(), -1.f,
                          std::numeric_limits<float>::infinity(), 2001.f}) {
        snapshot = valid;
        snapshot.sfa.ppb = invalid;
        std::feclearexcept(FE_INVALID);
        refresh();
        CheckColor(hcho_number, 0xADBEAF);
        CHECK(std::strcmp(lv_label_get_text(hcho_number), "—") == 0);
        view.Navigate(Page::Trend, false);
        Click(screen, "甲醛 HCHO");
        CheckColor(trend_number, 0x658475);
        CHECK(std::strcmp(lv_label_get_text(trend_number), "—") == 0);
        CHECK(!(std::fetestexcept(FE_INVALID) & FE_INVALID));
        view.Navigate(Page::Home, false);
    }
    state.SetTheme(true);
    refresh();
    CheckColor(hcho_number, 0xADBEAF);
    view.Navigate(Page::Trend, false);
    CheckColor(trend_number, 0xADBEAF);
    state.SetTheme(false);
    view.Navigate(Page::Home, false);
    // Disabling concentration alarms changes notification policy, never the reading colors.
    state.alerts.co2_enabled = state.alerts.hcho_enabled = false;
    snapshot = valid;
    snapshot.scd.ppm = 2400;
    snapshot.sfa.ppb = 90;
    refresh();
    CheckColor(co2_number, 0xBB3038);
    CheckColor(hcho_number, 0xFFBFC5);
    snapshot = saved_snapshot;
    state = saved_state;
    view.ApplyTheme();
    view.Navigate(Page::Trend, false);
    Click(screen, "甲醛 HCHO");  // Restore the metric selected by the preceding interaction tests.
    view.Navigate(saved_state.page(), false);
    view.SetAlerts(saved_alert, snapshot, power);
    refresh();
}
int main(int argc, char** argv) {
    lv_init();
    auto* display = lv_display_create(368, 448);
    std::vector<uint32_t> pixels(368 * 448);
    size_t flushes = 0;
    lv_display_set_user_data(display, &flushes);
    lv_display_set_color_format(display, LV_COLOR_FORMAT_ARGB8888);
    lv_display_set_buffers(display, pixels.data(), nullptr, pixels.size() * 4,
                           LV_DISPLAY_RENDER_MODE_DIRECT);
    lv_display_set_flush_cb(display, [](lv_display_t* d, const lv_area_t*, uint8_t*) {
        ++*static_cast<size_t*>(lv_display_get_user_data(d));
        lv_display_flush_ready(d);
    });
    AirUiState state;
    state.reduce_motion = true;
    uint64_t now = 1800000;
    // The device epoch already contains local fields; this is 2026-10-23 14:36 UTC.
    // A host timezone must not alter the displayed device-local time.
    std::time_t wall_time = 1792766160;
    int actions = 0, saves = 0, brightness = 0, history_reads = 0;
    int volume = -1, volume_commits = 0;
    int alert_acknowledgements = 0;
    uint32_t acknowledged_generation = 0;
    AirModel model;
    for (uint64_t t = 5000; t <= now; t += 5000) {
        if ((t / 5000) % 37 < 5)
            continue;
        model.ApplyScd41({static_cast<uint16_t>(700 + (t / 5000) % 300), 25.4f, 46}, t);
        model.ApplySfa40({18.f, 25.4f, 46, true, true, 0}, t);
    }
    AirViewCallbacks callbacks;
    callbacks.now_ms = [&]() { return now; };
    callbacks.wall_time = [&]() { return wall_time; };
    callbacks.preferences = [&]() { ++saves; };
    callbacks.brightness = [&](int value) { brightness = value; };
    callbacks.volume = [&](int value) {
        volume = value;
        ++volume_commits;
    };
    callbacks.acknowledge_alert = [&](uint32_t generation) {
        ++alert_acknowledgements;
        acknowledged_generation = generation;
    };
    callbacks.confirmed_action = [&](DeviceAction action) {
        CHECK(action == DeviceAction::Shutdown);
        ++actions;
    };
    callbacks.history = [&](Metric metric, std::array<HistoryPoint, kHistorySize>& out) {
        ++history_reads;
        out = model.History(metric);
    };
    AirView view(state, callbacks);
    auto* screen = lv_display_get_screen_active(display);
    view.Create(screen);
    CHECK(lv_obj_get_child_count(screen) > 0);
    auto count = lv_obj_get_child_count(screen);
    view.Create(screen);
    CHECK(lv_obj_get_child_count(screen) == count);
    auto snapshot = model.Snapshot(now);
    snapshot.scd.ppm = 864;
    PowerSnapshot power;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    auto* clock = Find(screen, "10-23 14:36");
    CHECK(clock);
    CHECK(Find(lv_obj_get_parent(clock), MATERIAL_SYMBOLS_WIFI));
    const char* directory = argc > 1 ? argv[1] : nullptr;
    CheckClockTransitions(view, state, snapshot, power, wall_time, screen, display, flushes, pixels,
                          directory);
    CheckGlyphs(screen);
    // An unchanged sample must not schedule any LCD transfers.
    lv_refr_now(display);
    flushes = 0;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    lv_refr_now(display);
    std::printf("unchanged home refresh: %zu flushes\n", flushes);
    CHECK(flushes == 0);
    const int history_reads_before_trend = history_reads;
    view.Navigate(Page::Trend, false);
    CHECK(history_reads == history_reads_before_trend + 1);
    lv_refr_now(display);
    flushes = 0;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    lv_refr_now(display);
    CHECK(flushes == 0);
    view.Navigate(Page::Home, false);
    view.Navigate(Page::Trend, false);
    CHECK(history_reads == history_reads_before_trend + 1);  // Reuse the prepared chart.
    view.Navigate(Page::Home, false);
    CHECK(Find(screen, "音量"));
    CHECK(Find(screen, "浓度提醒  ›"));
    auto* volume_slider = lv_obj_get_child(lv_obj_get_parent(Find(screen, "音量")), 2);
    CHECK(lv_obj_check_type(volume_slider, &lv_slider_class));
    view.SetVolume(37);
    CHECK(lv_slider_get_value(volume_slider) == 37 && Find(screen, "37%"));
    lv_obj_send_event(volume_slider, LV_EVENT_PRESSED, nullptr);
    lv_slider_set_value(volume_slider, 0, LV_ANIM_OFF);
    lv_obj_send_event(volume_slider, LV_EVENT_VALUE_CHANGED, nullptr);
    CHECK(Find(screen, "静音") && volume_commits == 0);
    view.SetVolume(80);  // An external update must not move a slider under the finger.
    CHECK(lv_slider_get_value(volume_slider) == 0);
    lv_obj_send_event(volume_slider, LV_EVENT_RELEASED, nullptr);
    CHECK(volume == 0 && volume_commits == 1);
    lv_obj_send_event(volume_slider, LV_EVENT_PRESS_LOST, nullptr);
    CHECK(volume_commits == 1);
    view.SetVolume(80);
    CHECK(lv_slider_get_value(volume_slider) == 80 && Find(screen, "80%"));
    view.SetVolume(200);
    CHECK(lv_slider_get_value(volume_slider) == 100 && Find(screen, "100%"));
    view.SetVolume(-1);
    CHECK(lv_slider_get_value(volume_slider) == 0 && Find(screen, "静音"));
    view.SetVolume(70);
    CHECK(volume_commits == 1 && saves == 0);
    Render(display, pixels, directory, "home-day");
    auto* co2_number = Find(screen, "864");
    auto* hcho_number = Find(screen, "18");
    CHECK(co2_number && hcho_number);
    CheckHchoStates(view, state, snapshot, power, lv_obj_get_parent(co2_number), hcho_number,
                    display, pixels, directory);
    for (const auto [value, color] : {std::pair{1000, 0x936200u}, {2000, 0xBB3038u}}) {
        snapshot.scd.ppm = value;
        view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
        CHECK(lv_color_eq(lv_obj_get_style_text_color(co2_number, LV_PART_MAIN),
                          lv_color_hex(color)));
    }
    snapshot.scd.ppm = 864;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    snapshot.hcho.environment_ok = false;
    snapshot.hcho.within_spec = false;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    CHECK(Find(screen, "部分异常"));
    auto* hcho_status = Find(screen, "超出额定条件");
    CHECK(hcho_status);
    lv_obj_update_layout(screen);
    CHECK(lv_obj_get_y(hcho_status) + lv_obj_get_height(hcho_status) <=
          lv_obj_get_height(lv_obj_get_parent(hcho_status)));
    Render(display, pixels, directory, "home-outside-spec");
    snapshot.hcho.environment_ok = snapshot.hcho.within_spec = true;
    snapshot.co2.within_spec = false;
    snapshot.scd.ppm = 65535;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    auto* five = Find(screen, "65535");
    CHECK(five);
    lv_obj_update_layout(screen);
    lv_point_t size;
    lv_text_get_size(&size, "65535", lv_obj_get_style_text_font(five, LV_PART_MAIN), 0, 0, 252,
                     LV_TEXT_FLAG_NONE);
    CHECK(size.x <= 252);
    Render(display, pixels, directory, "home-five-digits");
    snapshot.scd.ppm = 864;
    snapshot.co2.within_spec = true;
    Click(screen, MATERIAL_SYMBOLS_SETTINGS);
    CHECK(state.page() == Page::Settings);
    Render(display, pixels, directory, "settings-day");
    auto* settings_body = lv_obj_get_parent(lv_obj_get_parent(Find(screen, "音量")));
    view.SetVolume(0);
    Render(display, pixels, directory, "settings-muted");
    view.SetVolume(70);
    lv_obj_scroll_to_y(settings_body, 88, LV_ANIM_OFF);
    Render(display, pixels, directory, "settings-more");
    lv_obj_scroll_to_y(settings_body, 0, LV_ANIM_OFF);
    state.Notify("保存失败，设置暂存", now, 2000);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, false, "Wi-Fi 离线");
    auto* notice = Find(screen, "保存失败，设置暂存");
    CHECK(notice);
    CheckNoticeContrast(notice);
    for (auto* object = notice; object; object = lv_obj_get_parent(object))
        CHECK(!lv_obj_has_flag(object, LV_OBJ_FLAG_HIDDEN));
    Render(display, pixels, directory, "settings-notice");
    now += 2000;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    CHECK(!Find(screen, "保存失败，设置暂存"));
    Click(screen, "夜间");
    CHECK(state.night() && saves == 1);
    CHECK(state.theme_mode() == ThemeMode::Night);
    Click(screen, "自动");
    CHECK(state.theme_mode() == ThemeMode::Auto && state.night());
    Render(display, pixels, directory, "settings-auto-night");
    state.SetTheme(false);  // Apply the same state change as the sunrise adapter.
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    CHECK(state.theme_mode() == ThemeMode::Auto && !state.night());
    Render(display, pixels, directory, "settings-auto-day");
    Click(screen, "夜间");
    CHECK(state.night() && saves == 3);
    state.Notify("保存失败，设置暂存", now, 2000);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, false, "Wi-Fi 离线");
    CheckNoticeContrast(Find(screen, "保存失败，设置暂存"));
    Render(display, pixels, directory, "settings-notice-night");
    now += 2000;
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    view.Navigate(Page::Home, false);
    view.Refresh(snapshot, power, kDeviceStateListening, true, true, "Wi-Fi 已连接");
    view.WakeHome();
    Render(display, pixels, directory, "home-night");
    view.Navigate(Page::Trend, false);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    Render(display, pixels, directory, "trend-night");
    Click(screen, "甲醛 HCHO");
    CHECK(Find(screen, "ppb"));
    view.Navigate(Page::Settings, false);
    Click(screen, "传感器与连接  ›");
    CHECK(state.drawer());
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    CheckGlyphs(screen);
    Render(display, pixels, directory, "details-night");
    Click(screen, "关机");
    Render(display, pixels, directory, "confirmation-night");
    Click(screen, "取消");
    CHECK(actions == 0);
    Click(screen, "关机");
    view.WakeHome();
    CHECK(state.page() == Page::Home && !state.drawer());
    Click(screen, "确认");
    CHECK(actions == 0);
    view.RequestAction(DeviceAction::Shutdown);
    view.WakeHome();
    Click(screen, "确认");
    CHECK(actions == 0);
    view.Navigate(Page::Settings, false);
    Click(screen, "传感器与连接  ›");
    Click(screen, "关机");
    now += 30000;
    Click(screen, "确认");
    CHECK(actions == 0);
    Click(screen, "关机");
    Click(screen, "确认");
    CHECK(actions == 1);
    Click(screen, "确认");
    CHECK(actions == 1);
    for (int i = 0; i < 100; ++i) {
        state.SetTheme(i % 2);
        view.ApplyTheme();
        view.Navigate(static_cast<Page>(i % 3), false);
        view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    }
    CHECK(lv_obj_get_child_count(screen) == count);
    struct Pointer {
        int x = 0, y = 0;
        bool down = false;
    } pointer;
    const int prior_saves = saves;
    view.SetBrightness(0);
    CHECK(state.brightness() == 1 && brightness == 1 && saves == prior_saves + 1);
    CHECK(Find(screen, "1%"));
    view.SetBrightness(66);
    CHECK(state.brightness() == 66 && brightness == 66 && saves == prior_saves + 2);
    CHECK(Find(screen, "66%"));
    auto* input = lv_indev_create();
    lv_indev_set_type(input, LV_INDEV_TYPE_POINTER);
    lv_indev_set_display(input, display);
    lv_indev_set_user_data(input, &pointer);
    lv_indev_set_read_cb(input, [](lv_indev_t* in, lv_indev_data_t* data) {
        auto& p = *static_cast<Pointer*>(lv_indev_get_user_data(in));
        data->point = {p.x, p.y};
        data->state = p.down ? LV_INDEV_STATE_PRESSED : LV_INDEV_STATE_RELEASED;
    });
    auto touch = [&](int x, int y, bool down) {
        pointer = {x, y, down};
        lv_tick_inc(40);
        lv_indev_read(input);
        lv_timer_handler();
    };
    view.Navigate(Page::Home, false);
    lv_obj_update_layout(screen);
    touch(180, 230, true);
    touch(100, 230, true);
    touch(200, 230, true);
    touch(200, 230, false);
    CHECK(state.page() == Page::Home);
    view.Navigate(Page::Settings, false);
    lv_obj_update_layout(screen);
    // A vertical drag over plain settings text must reach the scrolling list.
    // Test actual input hit-testing; scroll_to_y alone cannot catch a dead region.
    lv_obj_scroll_to_y(settings_body, 0, LV_ANIM_OFF);
    touch(90, 270, true);
    touch(90, 250, true);
    touch(90, 230, true);
    touch(90, 210, true);
    CHECK(lv_obj_get_scroll_y(settings_body) > 20);
    touch(90, 210, false);
    lv_tick_inc(500);
    lv_timer_handler();
    lv_obj_scroll_to_y(settings_body, 0, LV_ANIM_OFF);
    // Repeated reversals must work from labels, card backgrounds and row gaps.
    for (auto start : {lv_point_t{90, 270}, lv_point_t{180, 162}, lv_point_t{180, 180}}) {
        lv_obj_scroll_to_y(settings_body, 0, LV_ANIM_OFF);
        lv_obj_update_layout(screen);
        touch(start.x, start.y, true);
        touch(start.x, start.y - 20, true);
        touch(start.x, start.y - 40, true);
        CHECK(lv_obj_get_scroll_y(settings_body) > 20);
        touch(start.x, start.y - 40, false);
        lv_tick_inc(500);
        lv_timer_handler();
        lv_obj_scroll_to_y(settings_body, 80, LV_ANIM_OFF);
        lv_obj_update_layout(screen);
        touch(90, 220, true);
        touch(90, 240, true);
        touch(90, 260, true);
        CHECK(lv_obj_get_scroll_y(settings_body) < 60);
        touch(90, 260, false);
        lv_tick_inc(500);
        lv_timer_handler();
    }
    lv_obj_scroll_to_y(settings_body, 0, LV_ANIM_OFF);
    lv_obj_update_layout(screen);
    const int brightness_before_vertical_drag = state.brightness();
    // A mainly vertical diagonal over a horizontal slider must scroll, not adjust it.
    touch(180, 130, true);
    touch(196, 98, true);
    CHECK(lv_obj_get_scroll_y(settings_body) > 0);
    CHECK(state.brightness() == brightness_before_vertical_drag);
    touch(196, 98, false);
    lv_tick_inc(500);
    lv_timer_handler();
    for (int direction : {-1, 1}) {
        const int offset = direction < 0 ? 40 : 100;
        lv_obj_scroll_to_y(settings_body, offset, LV_ANIM_OFF);
        lv_obj_update_layout(screen);
        const int before_value = lv_slider_get_value(volume_slider);
        const int before_commits = volume_commits;
        const int y = 222 - offset;
        touch(180, y, true);
        touch(196, y + direction * 32, true);
        CHECK(direction < 0 ? lv_obj_get_scroll_y(settings_body) > offset
                            : lv_obj_get_scroll_y(settings_body) < offset);
        touch(196, y + direction * 32, false);
        CHECK(lv_slider_get_value(volume_slider) == before_value);
        CHECK(volume_commits == before_commits);
        CHECK(state.page() == Page::Settings);
        lv_tick_inc(500);
        lv_timer_handler();
    }
    lv_obj_scroll_to_y(settings_body, 0, LV_ANIM_OFF);
    const int prior_brightness = state.brightness();
    touch(120, 130, true);
    touch(300, 130, true);
    touch(300, 130, false);
    CHECK(state.page() == Page::Settings && state.brightness() > prior_brightness);
    // Once a horizontal adjustment is claimed, later vertical drift must not steal it.
    const int before_volume_commits = volume_commits;
    touch(120, 222, true);
    touch(260, 222, true);
    touch(200, 84, true);
    CHECK(lv_obj_get_scroll_y(settings_body) == 0);
    touch(200, 84, false);
    CHECK(volume_commits == before_volume_commits + 1);
    CHECK(volume == lv_slider_get_value(volume_slider));
    CHECK(state.page() == Page::Settings);
    touch(10, 200, true);
    touch(120, 200, true);
    touch(120, 200, false);
    CHECK(state.page() == Page::Trend);
    state.reduce_motion = false;
    now += 5000;
    snapshot.now_ms = now;
    view.Navigate(Page::Home, false);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    lv_obj_update_layout(screen);
    const int reads_before_drag = history_reads;
    touch(180, 230, true);
    touch(100, 230, true);
    CHECK(history_reads == reads_before_drag + 1);  // Prepare the incoming chart now.
    auto* home_page = lv_obj_get_parent(co2_number);
    const int drag_x = lv_obj_get_x(home_page);
    CHECK(drag_x == -80);
    touch(100, 230, false);
    CHECK(state.page() == Page::Trend);
    CHECK(history_reads == reads_before_drag + 1);  // Release must reuse the preview.
    lv_obj_update_layout(screen);
    CHECK(lv_obj_get_x(home_page) <= drag_x);
    lv_tick_inc(250);
    lv_timer_handler();
    view.Navigate(Page::Settings, false);
    Click(screen, "浓度提醒  ›");
    Render(display, pixels, directory, "alert-settings");
    auto* co2_card = lv_obj_get_parent(Find(screen, "1500 ppm"));
    auto* limit = lv_obj_get_child(co2_card, 3);
    CHECK(lv_obj_check_type(limit, &lv_slider_class));
    const int before_limit_saves = saves;
    lv_slider_set_value(limit, 2130, LV_ANIM_OFF);
    lv_obj_send_event(limit, LV_EVENT_VALUE_CHANGED, nullptr);
    CHECK(state.alerts.co2_ppm == 2100 && Find(screen, "2100 ppm") && saves == before_limit_saves);
    lv_obj_send_event(limit, LV_EVENT_RELEASED, nullptr);
    CHECK(saves == before_limit_saves + 1);
    CHECK(!Find(screen, "预览告警"));
    auto* alert_settings = lv_obj_get_parent(Find(screen, "浓度提醒"));
    lv_obj_send_event(lv_obj_get_child(alert_settings, 0), LV_EVENT_CLICKED, nullptr);
    snapshot.scd.ppm = 2400;
    snapshot.now_ms = now;
    for (auto* channel : {&snapshot.co2, &snapshot.hcho})
        channel->last_frame_ms = channel->last_value_ms = now;
    view.Navigate(Page::Trend, false);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    AlertSnapshot alert{9, kAlertCo2, 0, kAlertCo2};
    view.SetAlerts(alert, snapshot, power);
    CHECK(state.page() == Page::Trend && !Find(screen, "知道了"));
    CHECK(alert_acknowledgements == 0 && acknowledged_generation == 0);
    view.Navigate(Page::Home, false);
    view.Refresh(snapshot, power, kDeviceStateIdle, true, true, "Wi-Fi 已连接");
    CheckColor(co2_number, 0xFFBFC5);
    view.RequestAction(DeviceAction::Shutdown);
    alert.generation = 10;
    view.SetAlerts(alert, snapshot, power);
    CHECK(Find(screen, "确认关机？"));
    Click(screen, "取消");
    CHECK(!Find(screen, "知道了"));
    CheckReadingColors(view, state, snapshot, power, alert, screen, co2_number, hcho_number,
                       display, pixels, directory);
    CheckGlyphs(screen);
    lv_indev_delete(input);
    std::puts(
        "view: native layout, glyphs, five digits, theme, pages and local confirmation passed");
}
