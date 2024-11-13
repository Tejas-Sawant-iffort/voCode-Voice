let socket;
let mediaRecorder;
let audioChunks = [];

// Initialize WebSocket connection
function connectWebSocket() {
    socket = new WebSocket("ws://localhost:8000/ws/audio");

    socket.onmessage = function(event) {
        const audioBlob = new Blob([event.data], { type: 'audio/wav' });
        const audioUrl = URL.createObjectURL(audioBlob);
        document.getElementById("audio-player").src = audioUrl;
    };

    socket.onclose = function() {
        console.log("WebSocket closed, reconnecting...");
        setTimeout(connectWebSocket, 1000);
    };
}

// Start recording and sending audio
function startRecording() {
    navigator.mediaDevices.getUserMedia({ audio: true })
        .then(stream => {
            mediaRecorder = new MediaRecorder(stream);
            mediaRecorder.start();

            mediaRecorder.ondataavailable = event => {
                audioChunks.push(event.data);
                if (socket.readyState === WebSocket.OPEN) {
                    socket.send(event.data); // Send audio chunk to WebSocket server
                }
            };

            mediaRecorder.onstop = () => {
                stream.getTracks().forEach(track => track.stop());
            };
        });
}

// Stop recording
function stopRecording() {
    mediaRecorder.stop();
    audioChunks = [];
}

// Connect WebSocket on load
connectWebSocket();
