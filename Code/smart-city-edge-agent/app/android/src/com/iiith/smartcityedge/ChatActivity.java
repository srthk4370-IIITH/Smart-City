package com.iiith.smartcityedge;

/** Second launcher icon, "Campus Assistant": the same backend, the chat frontend at web/chat/ (backend/chat.go). */
public class ChatActivity extends MainActivity {
    @Override
    protected String startPath() { return "chat/"; }
}
