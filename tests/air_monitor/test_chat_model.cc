#include "air_chat_model.h"
#include "test_support.h"

#include <cstring>
#include <limits>
#include <string>

using air::AirChatModel;
using Role = AirChatModel::Role;

namespace {
void RolesAndEmptyInput() {
    AirChatModel model;
    model.Append("system", "hidden");
    model.Append("other", "hidden");
    model.Append("User", "hidden");
    model.Append("user", "");
    model.Append("assistant", " \t\r\n");
    CHECK(model.messages().empty() && model.revision() == 0);
    model.Append("user", "你好");
    CHECK(model.messages().size() == 1);
    CHECK(model.messages()[0].role == Role::User);
    CHECK(model.messages()[0].text == "你好");
    CHECK(model.messages()[0].id != 0 && model.revision() == 1);
}

void AssistantSentences() {
    AirChatModel model;
    model.Append("user", "问题");
    model.Append("assistant", "第一句");
    CHECK(model.messages().size() == 2);
    const auto id = model.messages().back().id;
    model.Append("assistant", "第二句");
    CHECK(model.messages().size() == 2);
    CHECK(model.messages().back().text == "第一句\n第二句");
    CHECK(model.messages().back().id == id && model.revision() == 3);
    model.Append("user", "继续");
    model.Append("assistant", "第三句");
    CHECK(model.messages().size() == 4);
    CHECK(model.messages().back().role == Role::Assistant);
}

void MergeByteBoundary() {
    AirChatModel model;
    model.Append("assistant", std::string(766, 'a'));
    CHECK(model.messages().size() == 1);
    const auto id = model.messages().back().id;
    model.Append("assistant", "b");
    CHECK(model.messages().size() == 1 && model.messages()[0].text.size() == 768);
    CHECK(model.messages()[0].id == id && model.messages()[0].text.back() == 'b');
    model.Append("assistant", "c");
    CHECK(model.messages().size() == 2 && model.messages()[1].text == "c");
    model.Append("user", "x");
    model.Append("user", "x");
    CHECK(model.messages().size() == 4);
}

void BoundedHistory() {
    AirChatModel model;
    for (int i = 0; i < 20; ++i) {
        model.Append("user", "turn " + std::to_string(i));
    }
    CHECK(model.messages().size() == 16);
    CHECK(model.messages().front().text == "turn 4");
    CHECK(model.messages().back().text == "turn 19");
    CHECK(model.revision() == 20);
    for (size_t i = 1; i < model.messages().size(); ++i) {
        CHECK(model.messages()[i - 1].id < model.messages()[i].id);
    }
    const auto retained = model.messages()[1].id;
    model.Append("user", "new");
    CHECK(model.messages().front().id == retained);
}

void SplitLongInput() {
    AirChatModel model;
    const std::string text(769, 'x');
    model.Append("user", text);
    CHECK(model.messages().size() == 2);
    CHECK(model.messages()[0].text.size() == 768 && model.messages()[1].text == "x");
    CHECK(model.messages()[0].text + model.messages()[1].text == text);
    CHECK(model.revision() == 1);
    AirChatModel assistant;
    assistant.Append("assistant", text);
    CHECK(assistant.messages().size() == 2);
    CHECK(assistant.messages()[0].text + assistant.messages()[1].text == text);
}

void SplitUtf8Boundaries() {
    AirChatModel model;
    const std::string text = std::string(767, 'a') + "你🙂末";
    model.Append("assistant", text);
    CHECK(model.messages().size() == 2);
    CHECK(model.messages()[0].text == std::string(767, 'a'));
    CHECK(model.messages()[1].text == "你🙂末");
}

void InputByteLimit() {
    AirChatModel model;
    model.Append("user", std::string(2 * 1024 * 1024, 'a'));
    CHECK(model.messages().size() == 6);
    size_t total = 0;
    for (const auto& message : model.messages()) {
        CHECK(message.text.size() <= 768);
        total += message.text.size();
    }
    CHECK(total == 4096 && model.revision() == 1);
    AirChatModel boundary;
    boundary.Append("user", std::string(4095, 'a') + "你after");
    CHECK(boundary.messages().size() == 6);
    CHECK(boundary.messages().back().text == std::string(255, 'a'));
}

void SanitizeInvalidUtf8() {
    AirChatModel model;
    model.Append("user", "A\xf0\x28\x8c\x28Z");
    CHECK(model.messages().size() == 1 && model.messages()[0].text == "A?(?(Z");
    model.Append("user", "\xed\xa0\x80\xc0\xaf\xf4\x90\x80\x80\xff");
    CHECK(model.messages().back().text == "??????????");
    model.Append("user", "tail\xe4\xbd");
    CHECK(model.messages().back().text == "tail??");
}

void SanitizeControls() {
    AirChatModel model;
    const char text[] = "a\0b\1c\td\re\r\nf\n\xc2\x85g";
    model.Append("user", std::string_view(text, sizeof(text) - 1));
    CHECK(model.messages().size() == 1);
    CHECK(model.messages()[0].text == "abc d\ne\nf\ng");
    const auto revision = model.revision();
    model.Append("user", std::string_view("\0\1\x7f\xc2\x85", 5));
    CHECK(model.messages().size() == 1 && model.revision() == revision);
}

void RemoveLatestExactMatch() {
    AirChatModel model;
    model.Append("user", "same");
    CHECK(model.messages().size() == 1);
    const auto first_id = model.messages().back().id;
    model.Append("user", "different");
    const auto middle_id = model.messages().back().id;
    model.Append("user", "same");
    const auto last_id = model.messages().back().id;
    model.Remove("user", "same");
    CHECK(model.messages().size() == 2 && model.revision() == 4);
    CHECK(model.messages()[0].id == first_id && model.messages()[1].id == middle_id);
    model.Append("user", "new");
    CHECK(model.messages().back().id > last_id);
    const auto revision = model.revision();
    model.Remove("system", "same");
    model.Remove("user", "sam");
    model.Remove("user", "");
    CHECK(model.messages().size() == 3 && model.revision() == revision);
}

void RemoveCannotEraseMergedHint() {
    AirChatModel model;
    model.Append("assistant", "正在连接");
    model.Append("assistant", "正常回答");
    model.Remove("assistant", "正在连接");
    CHECK(model.messages().size() == 1 && model.revision() == 2);
    CHECK(model.messages()[0].text == "正在连接\n正常回答");
    model.Remove("assistant", "正在连接\n正常回答");
    CHECK(model.messages().empty() && model.revision() == 3);
    model.Append("user", std::string(769, 'x'));
    model.Remove("user", std::string(769, 'x'));
    CHECK(model.messages().size() == 2);
}

void IdleThirtySecondBoundary() {
    AirChatModel model;
    CHECK(!model.visible() && !model.active() && !model.browsing());
    CHECK(!model.Tick(999999));
    model.Open(1000);
    CHECK(model.visible());
    CHECK(!model.Tick(30999));
    CHECK(model.Tick(31000) && !model.visible());
    CHECK(!model.Tick(31001));
}

void ActiveEdgeAndManualClose() {
    AirChatModel model;
    model.Append("user", "保留");
    model.SetActive(true, 10);
    CHECK(model.active() && model.visible());
    CHECK(!model.Tick(100000));
    model.Close();
    CHECK(!model.visible() && model.active());
    model.SetActive(true, 100001);
    CHECK(!model.visible() && !model.Tick(200000));
    model.SetActive(false, 200001);
    CHECK(!model.active() && !model.visible());
    model.SetActive(true, 200002);
    CHECK(model.active() && model.visible() && model.messages().size() == 1);
    model.SetActive(false, 200010);
    CHECK(!model.Tick(230009));
    CHECK(model.Tick(230010));
}

void InteractRestartsIdle() {
    AirChatModel model;
    model.Open(0);
    CHECK(!model.Tick(29999));
    model.Interact(29999);
    CHECK(!model.Tick(30000));
    CHECK(!model.Tick(59998));
    CHECK(model.Tick(59999));
}

void BrowseLastsForVisit() {
    AirChatModel model;
    model.Open(0);
    model.Browse();
    CHECK(model.browsing() && !model.Tick(30000));
    model.Interact(40000);
    model.SetActive(false, 50000);
    CHECK(model.browsing() && !model.Tick(999999));
    model.Open(1000000);
    CHECK(!model.browsing() && !model.Tick(1029999));
    CHECK(model.Tick(1030000));
    model.Open(2000000);
    model.Browse();
    model.SetActive(true, 2000010);
    CHECK(model.visible() && !model.browsing());
    model.SetActive(false, 2000020);
    CHECK(model.Tick(2030020));
}

void BackgroundRestartsIdle() {
    AirChatModel model;
    model.Open(0);
    CHECK(!model.Tick(29999, false) && model.visible());
    CHECK(!model.Tick(100000, false) && model.visible());
    CHECK(!model.Tick(200000, true));
    CHECK(!model.Tick(229999, true));
    CHECK(model.Tick(230000, true));
}

void RepeatedIdleDoesNotPostpone() {
    AirChatModel model;
    model.Open(10);
    model.SetActive(false, 10000);
    CHECK(!model.Tick(30009));
    CHECK(model.Tick(30010));
}

void ClockOverflowAndRollback() {
    AirChatModel model;
    model.Open(std::numeric_limits<uint64_t>::max() - 100);
    CHECK(!model.Tick(std::numeric_limits<uint64_t>::max()));
    CHECK(!model.Tick(1) && model.visible());
    CHECK(!model.Tick(30000));
    CHECK(model.Tick(30001));
    model.Open(50000);
    CHECK(!model.Tick(40000));
    CHECK(!model.Tick(69999));
    CHECK(model.Tick(70000));
}

void ContentRevisionIgnoresPageState() {
    AirChatModel model;
    model.Append("user", "history");
    const auto revision = model.revision();
    model.Open(0);
    model.Interact(1);
    model.Browse();
    model.Close();
    model.SetActive(true, 3);
    model.SetActive(false, 4);
    CHECK(model.Tick(30004));
    CHECK(model.messages().size() == 1 && model.messages()[0].text == "history");
    CHECK(model.revision() == revision);
}
}  // namespace

int main(int argc, char** argv) {
    struct Test {
        const char* name;
        void (*run)();
    };
    const Test tests[] = {{"roles", RolesAndEmptyInput},
                          {"assistant", AssistantSentences},
                          {"merge-boundary", MergeByteBoundary},
                          {"history", BoundedHistory},
                          {"split", SplitLongInput},
                          {"utf8-boundary", SplitUtf8Boundaries},
                          {"input-limit", InputByteLimit},
                          {"utf8-invalid", SanitizeInvalidUtf8},
                          {"controls", SanitizeControls},
                          {"remove", RemoveLatestExactMatch},
                          {"remove-merged", RemoveCannotEraseMergedHint},
                          {"idle", IdleThirtySecondBoundary},
                          {"active-edge", ActiveEdgeAndManualClose},
                          {"interact", InteractRestartsIdle},
                          {"browse", BrowseLastsForVisit},
                          {"background", BackgroundRestartsIdle},
                          {"repeated-idle", RepeatedIdleDoesNotPostpone},
                          {"overflow", ClockOverflowAndRollback},
                          {"revision", ContentRevisionIgnoresPageState}};
    size_t count = 0;
    for (const auto& test : tests) {
        if (argc == 1 || std::strcmp(argv[1], test.name) == 0) {
            test.run();
            ++count;
        }
    }
    CHECK(count != 0);
    std::printf("chat_model: %zu bounded input, history and timing checks passed\n", count);
}
