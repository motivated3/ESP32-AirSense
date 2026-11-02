#include "air_chat_model.h"

#include <algorithm>

namespace air {
namespace {
bool ParseRole(std::string_view name, AirChatModel::Role& role) {
    if (name == "user") {
        role = AirChatModel::Role::User;
    } else if (name == "assistant") {
        role = AirChatModel::Role::Assistant;
    } else {
        return false;
    }
    return true;
}

std::string Sanitize(std::string_view input) {
    const bool clipped = input.size() > AirChatModel::kInputBytes;
    input = input.substr(0, AirChatModel::kInputBytes);
    std::string text;
    text.reserve(input.size());
    for (size_t offset = 0; offset < input.size();) {
        const auto first = static_cast<uint8_t>(input[offset]);
        if (first < 0x80) {
            ++offset;
            if (first == '\r') {
                text += '\n';
                if (offset < input.size() && input[offset] == '\n') {
                    ++offset;
                }
            } else if (first == '\t') {
                text += ' ';
            } else if (first == '\n' || (first >= 0x20 && first != 0x7f)) {
                text += static_cast<char>(first);
            }
            continue;
        }
        const size_t bytes = first >= 0xc2 && first <= 0xdf   ? 2
                             : first >= 0xe0 && first <= 0xef ? 3
                             : first >= 0xf0 && first <= 0xf4 ? 4
                                                              : 0;
        if (bytes != 0 && offset + bytes > input.size() && clipped) {
            break;  // A bounded input must never retain half a codepoint.
        }
        bool valid = bytes != 0 && offset + bytes <= input.size();
        uint32_t codepoint = bytes == 0 ? 0 : first & (0x7f >> bytes);
        for (size_t i = 1; valid && i < bytes; ++i) {
            const auto next = static_cast<uint8_t>(input[offset + i]);
            valid = (next & 0xc0) == 0x80;
            codepoint = (codepoint << 6) | (next & 0x3f);
        }
        valid = valid && (bytes != 3 || codepoint >= 0x800) &&
                (bytes != 4 || codepoint >= 0x10000) && codepoint <= 0x10ffff &&
                !(codepoint >= 0xd800 && codepoint <= 0xdfff);
        if (!valid) {
            text += '?';
            ++offset;
        } else {
            if (codepoint >= 0xa0) {  // Drop C1 controls, including the encoded NEL.
                text.append(input.substr(offset, bytes));
            }
            offset += bytes;
        }
    }
    if (text.find_first_not_of(" \n") == std::string::npos) {
        text.clear();
    }
    return text;
}
}  // namespace

void AirChatModel::Append(std::string_view role, std::string_view text) {
    Role parsed;
    if (!ParseRole(role, parsed)) {
        return;
    }
    const auto clean = Sanitize(text);
    if (clean.empty()) {
        return;
    }
    for (size_t offset = 0; offset < clean.size();) {
        size_t end = std::min(offset + kMessageBytes, clean.size());
        while (end < clean.size() && (static_cast<uint8_t>(clean[end]) & 0xc0) == 0x80) {
            --end;
        }
        const std::string_view chunk(clean.data() + offset, end - offset);
        if (parsed == Role::Assistant && !messages_.empty() && messages_.back().role == parsed &&
            messages_.back().text.size() + 1 + chunk.size() <= kMessageBytes) {
            messages_.back().text += '\n';
            messages_.back().text.append(chunk);
        } else {
            if (messages_.size() == kCapacity) {
                messages_.erase(messages_.begin());
            }
            uint32_t id;
            do {
                id = next_id_++;
            } while (id == 0 ||
                     std::any_of(messages_.begin(), messages_.end(),
                                 [id](const Message& message) { return message.id == id; }));
            messages_.push_back({id, parsed, std::string(chunk)});
        }
        offset = end;
    }
    ++revision_;
}

void AirChatModel::Remove(std::string_view role, std::string_view text) {
    Role parsed;
    if (!ParseRole(role, parsed) || text.size() > kInputBytes) {
        return;
    }
    const auto clean = Sanitize(text);
    if (clean.empty() || clean.size() > kMessageBytes) {
        return;
    }
    for (size_t i = messages_.size(); i > 0; --i) {
        if (messages_[i - 1].role == parsed && messages_[i - 1].text == clean) {
            messages_.erase(messages_.begin() + (i - 1));
            ++revision_;
            return;
        }
    }
}

void AirChatModel::Open(uint64_t now_ms) {
    visible_ = true;
    browsing_ = false;
    Interact(now_ms);
}

void AirChatModel::Close() {
    visible_ = false;
    idle_armed_ = false;
}

void AirChatModel::SetActive(bool active, uint64_t now_ms) {
    if (active_ == active) {
        return;
    }
    active_ = active;
    if (active) {
        Open(now_ms);
    } else {
        Interact(now_ms);
    }
}

void AirChatModel::Interact(uint64_t now_ms) {
    idle_armed_ = visible_ && !active_ && !browsing_;
    idle_since_ms_ = now_ms;
}

void AirChatModel::Browse() {
    if (visible_) {
        browsing_ = true;
        idle_armed_ = false;
    }
}

bool AirChatModel::Tick(uint64_t now_ms, bool foreground) {
    if (!visible_ || active_ || browsing_ || !foreground) {
        idle_armed_ = false;
        return false;
    }
    if (!idle_armed_ || now_ms < idle_since_ms_) {
        Interact(now_ms);
        return false;
    }
    if (now_ms - idle_since_ms_ < 30000) {
        return false;
    }
    Close();
    return true;
}
}  // namespace air
