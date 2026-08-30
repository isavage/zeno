document.addEventListener("DOMContentLoaded", () => {
    const chatMessages = document.getElementById("chatMessages");
    const chatForm = document.getElementById("chatForm");
    const messageInput = document.getElementById("messageInput");
    const micBtn = document.getElementById("micBtn");
    const voiceStatus = document.getElementById("voiceStatus");
    const clearChatBtn = document.getElementById("clearChatBtn");
    const newChatBtn = document.getElementById("newChatBtn");
    const audioPlayer = document.getElementById("audioPlayer");
    const voiceToggleBtn = document.getElementById("voiceToggleBtn");
    const voiceToggleLabel = document.getElementById("voiceToggleLabel");
    const voiceTranscript = document.getElementById("voiceTranscript");
    const chatList = document.getElementById("chatList");

    let mediaRecorder = null;
    let mediaStream = null;
    let audioContext = null;
    let analyser = null;
    let silenceMonitorId = null;
    let audioChunks = [];
    let isRecording = false;
    let speechRecognition = null;
    let recordingDraftMessage = null;
    let activeChatId = localStorage.getItem("zenoActiveChatId") || "default";
    let chatCache = [];
    let voiceRepliesEnabled = localStorage.getItem("zenoVoiceReplies");
    voiceRepliesEnabled = voiceRepliesEnabled === null ? true : voiceRepliesEnabled === "true";

    const SILENCE_THRESHOLD = 0.02;
    const SILENCE_DURATION_MS = 2000;
    let lastVoiceActivityAt = 0;

    function updateVoiceToggleUI() {
        if (!voiceToggleBtn || !voiceToggleLabel) return;
        voiceToggleBtn.classList.toggle("voice-off", !voiceRepliesEnabled);
        voiceToggleBtn.classList.toggle("voice-on", voiceRepliesEnabled);
        voiceToggleLabel.textContent = voiceRepliesEnabled ? "Voice On" : "Voice Off";
        voiceToggleBtn.title = voiceRepliesEnabled ? "Voice replies are on" : "Voice replies are off";
    }

    function shouldPlayVoiceReply(data) {
        return voiceRepliesEnabled && data && data.audio_url;
    }

    function currentChatLabel(chat) {
        if (!chat) return "Default Chat";
        return chat.title || (chat.is_default ? "Default Chat" : "New Chat");
    }

    function renderChatList(chats) {
        if (!chatList) return;
        chatList.innerHTML = "";

        if (!chats.length) {
            const empty = document.createElement("div");
            empty.className = "chat-list-empty";
            empty.textContent = "No chats yet";
            chatList.appendChild(empty);
            return;
        }

        for (const chat of chats) {
            const item = document.createElement("button");
            item.type = "button";
            item.className = "chat-list-item";
            if (chat.chat_id === activeChatId) {
                item.classList.add("active");
            }
            item.dataset.chatId = chat.chat_id;
            item.innerHTML = `
                <span class="chat-list-title">${currentChatLabel(chat)}</span>
                <span class="chat-list-meta">${chat.is_default ? "Default" : "Chat"}</span>
            `;
            item.addEventListener("click", () => selectChat(chat.chat_id));
            chatList.appendChild(item);
        }
    }

    async function fetchChats() {
        const resp = await fetch("/api/chats");
        if (!resp.ok) {
            throw new Error("Failed to load chats");
        }
        const data = await resp.json();
        chatCache = data.chats || [];
        return chatCache;
    }

    function renderMessages(messages) {
        chatMessages.innerHTML = "";
        if (!messages.length) {
            chatMessages.innerHTML = `
                <div class="message assistant-message">
                    <div class="message-bubble">
                        <p>👋 Hello! I am <strong>Zeno</strong>, your private personal AI assistant. How can I help you today?</p>
                    </div>
                </div>
            `;
            return;
        }

        for (const message of messages) {
            appendMessage(message.role, message.content, message);
        }
    }

    async function loadChatHistory(chatId) {
        const resp = await fetch(`/api/chats/${encodeURIComponent(chatId)}/history`);
        if (!resp.ok) {
            throw new Error("Failed to load chat history");
        }
        const data = await resp.json();
        renderMessages(data.messages || []);
    }

    async function refreshChats() {
        const chats = await fetchChats();
        if (!chats.some((chat) => chat.chat_id === activeChatId)) {
            activeChatId = chats[0]?.chat_id || "default";
            localStorage.setItem("zenoActiveChatId", activeChatId);
        }
        renderChatList(chats);
    }

    async function selectChat(chatId) {
        activeChatId = chatId;
        localStorage.setItem("zenoActiveChatId", activeChatId);
        await refreshChats();
        await loadChatHistory(activeChatId);
    }

    async function createNewChat() {
        const resp = await fetch("/api/chats", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ title: "New Chat" }),
        });
        if (!resp.ok) {
            throw new Error("Failed to create chat");
        }
        const data = await resp.json();
        const created = data.chat;
        activeChatId = created.chat_id;
        localStorage.setItem("zenoActiveChatId", activeChatId);
        await refreshChats();
        await loadChatHistory(activeChatId);
    }

    function updateLiveTranscript(text) {
        if (!voiceTranscript) return;
        const clean = (text || "").trim();
        voiceTranscript.textContent = clean;
        voiceTranscript.classList.toggle("hidden", !clean);
    }

    function stopSpeechRecognition() {
        if (speechRecognition) {
            try {
                speechRecognition.onresult = null;
                speechRecognition.onend = null;
                speechRecognition.onerror = null;
                speechRecognition.stop();
            } catch (err) {
                // Ignore stop errors if recognition has already ended.
            }
            speechRecognition = null;
        }
    }

    function stopSilenceMonitor() {
        if (silenceMonitorId) {
            clearInterval(silenceMonitorId);
            silenceMonitorId = null;
        }
        if (audioContext) {
            audioContext.close().catch(() => {});
            audioContext = null;
            analyser = null;
        }
        mediaStream = null;
    }

    function startSilenceMonitor(stream) {
        const AudioContext = window.AudioContext || window.webkitAudioContext;
        if (!AudioContext) return;

        audioContext = new AudioContext();
        const source = audioContext.createMediaStreamSource(stream);
        analyser = audioContext.createAnalyser();
        analyser.fftSize = 2048;
        source.connect(analyser);

        const samples = new Uint8Array(analyser.fftSize);
        lastVoiceActivityAt = Date.now();

        silenceMonitorId = setInterval(() => {
            if (!analyser || !isRecording) return;
            analyser.getByteTimeDomainData(samples);
            let sumSquares = 0;
            for (let i = 0; i < samples.length; i += 1) {
                const normalized = (samples[i] - 128) / 128;
                sumSquares += normalized * normalized;
            }
            const rms = Math.sqrt(sumSquares / samples.length);
            if (rms > SILENCE_THRESHOLD) {
                lastVoiceActivityAt = Date.now();
            } else if (Date.now() - lastVoiceActivityAt > SILENCE_DURATION_MS) {
                stopRecording();
            }
        }, 100);
    }

    updateVoiceToggleUI();

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
            await fetch(`/api/chats/${encodeURIComponent(activeChatId)}/clear`, { method: "POST" });
            await loadChatHistory(activeChatId);
        }
    });

    if (newChatBtn) {
        newChatBtn.addEventListener("click", async () => {
            const resp = await fetch("/api/chats", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ title: "New Chat" }),
            });
            if (!resp.ok) return;
            const data = await resp.json();
            activeChatId = data.chat.chat_id;
            localStorage.setItem("zenoActiveChatId", activeChatId);
            await refreshChats();
            await loadChatHistory(activeChatId);
        });
    }

    if (voiceToggleBtn) {
        voiceToggleBtn.addEventListener("click", () => {
            voiceRepliesEnabled = !voiceRepliesEnabled;
            localStorage.setItem("zenoVoiceReplies", String(voiceRepliesEnabled));
            updateVoiceToggleUI();
        });
    }

    // Append Message to UI
    function appendMessage(role, text, meta = null) {
        const msgDiv = document.createElement("div");
        msgDiv.className = `message ${role}-message`;

        const bubble = document.createElement("div");
        bubble.className = "message-bubble";
        bubble.innerHTML = marked.parse(text || "");
        msgDiv.appendChild(bubble);
        msgDiv._bubble = bubble;

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

    function updateMessageText(messageEl, text) {
        if (!messageEl || !messageEl._bubble) return;
        messageEl._bubble.innerHTML = marked.parse(text || "");
        chatMessages.scrollTop = chatMessages.scrollHeight;
    }

    function parseSSEBlock(block) {
        let event = "message";
        const dataLines = [];
        for (const line of block.split("\n")) {
            if (line.startsWith("event:")) {
                event = line.slice(6).trim();
            } else if (line.startsWith("data:")) {
                dataLines.push(line.slice(5).trimStart());
            }
        }
        const dataText = dataLines.join("\n");
        let data = null;
        if (dataText) {
            try {
                data = JSON.parse(dataText);
            } catch (err) {
                data = { text: dataText };
            }
        }
        return { event, data };
    }

    async function consumeSSEResponse(resp, handlers) {
        if (!resp.body) {
            throw new Error("Streaming response body not available.");
        }

        const reader = resp.body.getReader();
        const decoder = new TextDecoder();
        let buffer = "";

        while (true) {
            const { value, done } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });

            let boundaryIndex = buffer.indexOf("\n\n");
            while (boundaryIndex !== -1) {
                const block = buffer.slice(0, boundaryIndex).trim();
                buffer = buffer.slice(boundaryIndex + 2);
                if (block) {
                    const { event, data } = parseSSEBlock(block);
                    if (handlers[event]) {
                        handlers[event](data || {});
                    }
                }
                boundaryIndex = buffer.indexOf("\n\n");
            }
        }

        buffer += decoder.decode();
        const finalBlock = buffer.trim();
        if (finalBlock) {
            const { event, data } = parseSSEBlock(finalBlock);
            if (handlers[event]) {
                handlers[event](data || {});
            }
        }
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
        let loadingDiv = appendMessage("assistant", "Thinking...");
        let assistantDraft = null;
        let assistantText = "";

        try {
            const resp = await fetch("/api/chat", {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({
                    message: text,
                    synthesize_voice: voiceRepliesEnabled,
                    chat_id: activeChatId,
                })
            });
            if (!resp.ok) {
                throw new Error("Chat request failed.");
            }

            await consumeSSEResponse(resp, {
                delta: (data) => {
                    if (!assistantDraft) {
                        loadingDiv.remove();
                        assistantDraft = appendMessage("assistant", "");
                    }
                    assistantText += data.text || "";
                    updateMessageText(assistantDraft, assistantText);
                },
                done: (data) => {
                    if (!assistantDraft) {
                        loadingDiv.remove();
                        assistantDraft = appendMessage("assistant", data.response || "", data);
                    } else {
                        updateMessageText(assistantDraft, data.response || assistantText);
                    }
                    refreshChats().catch(() => {});
                    if (shouldPlayVoiceReply(data)) {
                        audioPlayer.src = data.audio_url;
                        audioPlayer.play().catch(() => console.log("Audio autoplay prevented"));
                    }
                },
                error: () => {
                    if (loadingDiv) loadingDiv.remove();
                    appendMessage("assistant", "⚠️ Error communicating with Zeno.");
                },
            });
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
            mediaStream = await navigator.mediaDevices.getUserMedia({ audio: true });
            mediaRecorder = new MediaRecorder(mediaStream);
            audioChunks = [];
            updateLiveTranscript("");
            recordingDraftMessage = appendMessage("user", "🎙️ Listening...");

            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (SpeechRecognition) {
                speechRecognition = new SpeechRecognition();
                speechRecognition.lang = "en-US";
                speechRecognition.interimResults = true;
                speechRecognition.continuous = true;

                let finalTranscript = "";
                speechRecognition.onresult = (event) => {
                    let interimTranscript = "";
                    for (let i = event.resultIndex; i < event.results.length; i += 1) {
                        const transcript = event.results[i][0].transcript;
                        if (event.results[i].isFinal) {
                            finalTranscript += transcript;
                        } else {
                            interimTranscript += transcript;
                        }
                    }
                    const transcriptText = (finalTranscript + " " + interimTranscript).trim();
                    updateLiveTranscript(transcriptText);
                    if (recordingDraftMessage) {
                        updateMessageText(recordingDraftMessage, transcriptText ? `🎙️ *"${transcriptText}"*` : "🎙️ Listening...");
                    }
                };

                speechRecognition.onerror = () => {
                    stopSpeechRecognition();
                };

                speechRecognition.onend = () => {
                    // Keep the last transcript visible until the recording is sent or canceled.
                };

                try {
                    speechRecognition.start();
                } catch (err) {
                    // If the browser refuses to start recognition, keep audio recording only.
                }
            }

            mediaRecorder.ondataavailable = (event) => {
                if (event.data.size > 0) {
                    audioChunks.push(event.data);
                }
            };

            mediaRecorder.onstop = async () => {
                const audioBlob = new Blob(audioChunks, { type: "audio/webm" });
                if (mediaStream) {
                    mediaStream.getTracks().forEach(track => track.stop());
                }
                stopSilenceMonitor();
                stopSpeechRecognition();
                await sendVoiceNote(audioBlob);
            };

            mediaRecorder.start();
            isRecording = true;
            micBtn.classList.add("recording");
            voiceStatus.classList.remove("hidden");
            startSilenceMonitor(mediaStream);
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
        formData.append("synthesize_voice", String(voiceRepliesEnabled));
        formData.append("chat_id", activeChatId);

        const loadingDiv = appendMessage("assistant", "🎙️ Transcribing and thinking...");

        try {
            const resp = await fetch("/api/voice", {
                method: "POST",
                body: formData
            });
            if (!resp.ok) {
                throw new Error("Voice request failed.");
            }

            let userTranscriptAppended = false;
            let assistantDraft = null;
            let assistantText = "";

            await consumeSSEResponse(resp, {
                transcription: (data) => {
                    updateLiveTranscript(data.transcription || "");
                    if (data.transcription && !userTranscriptAppended) {
                        if (recordingDraftMessage) {
                            updateMessageText(recordingDraftMessage, `🎙️ *"${data.transcription}"*`);
                            recordingDraftMessage = null;
                        } else {
                            appendMessage("user", `🎙️ *"${data.transcription}"*`);
                        }
                        userTranscriptAppended = true;
                    }
                },
                delta: (data) => {
                    if (!assistantDraft) {
                        loadingDiv.remove();
                        assistantDraft = appendMessage("assistant", "");
                    }
                    assistantText += data.text || "";
                    updateMessageText(assistantDraft, assistantText);
                },
                done: (data) => {
                    if (!data.transcription && recordingDraftMessage) {
                        updateMessageText(recordingDraftMessage, "🎙️ _No speech detected._");
                        recordingDraftMessage = null;
                    }
                    if (!userTranscriptAppended && data.transcription) {
                        if (recordingDraftMessage) {
                            updateMessageText(recordingDraftMessage, `🎙️ *"${data.transcription}"*`);
                            recordingDraftMessage = null;
                        } else {
                            appendMessage("user", `🎙️ *"${data.transcription}"*`);
                        }
                    }
                    updateLiveTranscript(data.transcription || "");
                    if (!assistantDraft) {
                        loadingDiv.remove();
                        assistantDraft = appendMessage("assistant", data.response || "", data);
                    } else {
                        updateMessageText(assistantDraft, data.response || assistantText);
                    }
                    refreshChats().catch(() => {});
                    if (shouldPlayVoiceReply(data)) {
                        audioPlayer.src = data.audio_url;
                        audioPlayer.play().catch(() => console.log("Audio autoplay prevented"));
                    }
                },
                error: () => {
                    loadingDiv.remove();
                    appendMessage("assistant", "⚠️ Error processing voice note.");
                },
            });
        } catch (err) {
            loadingDiv.remove();
            appendMessage("assistant", "⚠️ Error processing voice note.");
        }
    }

    async function bootstrap() {
        await refreshChats();
        await loadChatHistory(activeChatId);
    }

    bootstrap().catch(() => {
        renderChatList([]);
    });
});
