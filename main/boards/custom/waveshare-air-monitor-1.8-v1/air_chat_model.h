#pragma once
#include <cstddef>
#include <cstdint>
#include <string>
#include <string_view>
#include <vector>

namespace air {
class AirChatModel {
public:
    enum class Role { User, Assistant };
    struct Message {
        uint32_t id;
        Role role;
        std::string text;
    };
    static constexpr size_t kCapacity = 16;
    static constexpr size_t kMessageBytes = 768;
    static constexpr size_t kInputBytes = 4096;

    const std::vector<Message>& messages() const { return messages_; }
    uint32_t revision() const { return revision_; }
    void Append(std::string_view role, std::string_view text);
    void Remove(std::string_view role, std::string_view text);
    void Open(uint64_t now_ms);
    void Close();
    void SetActive(bool active, uint64_t now_ms);
    void Interact(uint64_t now_ms);
    void Browse();
    bool Tick(uint64_t now_ms, bool foreground = true);
    bool visible() const { return visible_; }
    bool browsing() const { return browsing_; }
    bool active() const { return active_; }

private:
    std::vector<Message> messages_;
    uint32_t revision_ = 0;
    uint32_t next_id_ = 1;
    uint64_t idle_since_ms_ = 0;
    bool visible_ = false;
    bool browsing_ = false;
    bool active_ = false;
    bool idle_armed_ = false;
};
}  // namespace air
