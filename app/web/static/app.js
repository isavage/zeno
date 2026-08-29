document.addEventListener("DOMContentLoaded", () => {
    const chatMessages = document.getElementById("chatMessages");
    const chatForm = document.getElementById("chatForm");
    const messageInput = document.getElementById("messageInput");
    const micBtn = document.getElementById("micBtn");
    const voiceStatus = document.getElementById("voiceStatus");
    const clearChatBtn = document.getElementById("clearChatBtn");
    const audioPlayer = document.getElementById("audioPlayer");

    let mediaRecorder = null;
    let audioChunks = [];
    let isRecording = false;

    // Auto-resize textarea
    messageInput.addEventListener("input", () => {
        messageInput.style.height = "auto";
        messageInput.style.height = Math.min(messageInput.scrollHeight, 120) + "px";
    });

    // Handle Enter key for sending (Shift+Enter for newline)
    messageInput.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
            e.preventDefault();
            chatForm.dispatchEvent(new Event("submit"));
        }
    });

    // Clear chat
    clearChatBtn.addEventListener("click", async () => {
        if (confirm("Clear conversation context?")) {
            await fetch("/api/clear", { method: "POST" });
            chatMessages.innerHTML = `
                <div class="message assistant-message">
                    <div class="message-bubble">
                        <p>🧹 Conversation history cleared. How can I help you next?</p>
                    </div>
                </div>
            `;
        }
    });

    // Append Message to UI
    function appendMessage(role, text, meta = null) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role}-message`;

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.innerHTML = marked.parse(text || "");
        msgDiv.appendChild(bubble);

        if (meta && (meta.model_used || meta.tools_called?.length)) {
            const metaDiv = document.createElement("div");
            metaDiv.className = "message-meta";
            if (meta.model_used && meta.model_used !== "none") {
                metaDiv.innerHTML += `<span>⚡ ${meta.model_used}</span>`;
            }
            if (meta.tools_called && meta.tools_called.length > 0) {
                metaDiv.innerHTML += `<span class="tool-badge">🔧 ${meta.tools_called.join(", ")}</span>`;
            }
            msgDiv.appendChild(metaDiv);
        }

        chatMessages.appendChild(msgDiv);
        chatMessages.scrollTop = chatMessages.scrollHeight;
        return msgDiv;
    }

    // Submit Text Message
    chatForm.addEventListener("submit", async (e) => {
        e.preventDefault();
        const text = messageInput.value.trim();
        if (!text) return;

        messageInput.value = "";
        messageInput.style.height = "auto";
        appendMessage("user", text);

        // Add loading placeholder
        const loadingDiv = appendMessage("assistant", "Thinking...");

        try {
            const resp = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ message: text })
            });
            const data = await resp.json();
            loadingDiv.remove();
            appendMessage("assistant", data.response, data);

            if (data.audio_url) {
                audioPlayer.src = data.audio_url;
                audioPlayer.play().catch(e => console.log("Audio autoplay prevented"));
            }
        } catch (err) {
            loadingDiv.remove();
            appendMessage("assistant", "⚠️ Error communicating with Zeno.");
        }
    });

    // Voice Mode: Microphone Recording
    micBtn.addEventListener("click", async () => {
        if (!isRecording) {
            startRecording();
        } else {
            stopRecording();
        }
    });

    async function startRecording() {
        try {
            const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(stream);
            audioChunks = [];

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
                stream.getTracks().forEach(track => track.stop());
                await sendVoiceNote(audioBlob);
            };

            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add("recording");
            voiceStatus.classList.remove("hidden");
        } catch (err) {
            alert("Microphone access is required for voice mode.");
        }
    }

    function stopRecording() {
        if (mediaRecorder && isRecording) {
            mediaRecorder.stop();
            isRecording = false;
            micBtn.classList.remove("recording");
            voiceStatus.classList.add("hidden");
        }
    }

    async function sendVoiceNote(audioBlob) {
        const formData = new FormData();
        formData.append("file", audioBlob, "voice_recording.webm");

        const loadingDiv = appendMessage("assistant", "🎙️ Transcribing and thinking...");

        try {
            const resp = await fetch("/api/voice", {
                method: "POST",
                body: formData
            });
            const data = await resp.json();
            loadingDiv.remove();

            if (data.transcription) {
                appendMessage("user", `🎙️ *"${data.transcription}"*`);
            }
            appendMessage("assistant", data.response, data);

            if (data.audio_url) {
                audioPlayer.src = data.audio_url;
                audioPlayer.play().catch(e => console.log("Audio autoplay prevented"));
            }
        } catch (err) {
            loadingDiv.remove();
            appendMessage("assistant", "⚠️ Error processing voice note.");
        }
    }
});
