// Live dashboard. The camera only starts when the user presses "Start camera".
(function () {
    var EMOTIONS = ['Happy', 'Sad', 'Surprise', 'Angry', 'Fear', 'Disgust', 'Neutral'];
    var csrfMeta = document.querySelector('meta[name="csrf-token"]');
    var csrfToken = csrfMeta ? csrfMeta.getAttribute('content') : '';

    var video = document.getElementById('webcam');
    var overlay = document.getElementById('overlay');
    var ctx = overlay.getContext('2d');
    var hidden = document.getElementById('hidden-canvas');
    var hCtx = hidden.getContext('2d');
    var placeholder = document.getElementById('camera-placeholder');
    var cameraBtn = document.getElementById('camera-btn');
    var cameraLabel = document.getElementById('camera-btn-label');
    var snapBtn = document.getElementById('snapshot-btn');
    var statusEl = document.getElementById('status');

    var socket = null;
    var stream = null;
    var timer = null;
    var waiting = false;

    function setStatus(text, kind) {
        statusEl.textContent = text;
        statusEl.className = 'status-msg' + (kind === 'ok' ? ' is-ok' : kind === 'err' ? ' is-err' : '');
    }

    function connect() {
        if (socket) return;
        socket = io({ transports: ['websocket', 'polling'] });
        socket.on('connect', function () { setStatus('Connected. Analysing…', 'ok'); });
        socket.on('disconnect', function () { setStatus('Connection lost. Retrying…', 'err'); });
        socket.on('connect_error', function () { setStatus('Could not connect. Please refresh and sign in again.', 'err'); });
        socket.on('emotion_results', onResults);
    }

    async function startCamera() {
        if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
            setStatus('Your browser does not support camera access. Try a recent Chrome, Edge, Firefox or Safari.', 'err');
            return;
        }
        if (location.protocol !== 'https:' && location.hostname !== 'localhost' && location.hostname !== '127.0.0.1') {
            setStatus('The camera only works over a secure (https) connection.', 'err');
            return;
        }
        cameraBtn.disabled = true;
        setStatus('Asking for camera permission…');
        try {
            stream = await navigator.mediaDevices.getUserMedia({ video: { width: 1280, height: 720, frameRate: 15 } });
        } catch (err) {
            cameraBtn.disabled = false;
            setStatus('Camera access was blocked. Allow it in your browser settings, then try again.', 'err');
            return;
        }
        video.srcObject = stream;
        video.onloadedmetadata = function () {
            overlay.width = video.videoWidth;
            overlay.height = video.videoHeight;
            hidden.width = 320;
            hidden.height = Math.round((320 / video.videoWidth) * video.videoHeight);
            placeholder.classList.add('is-hidden');
            video.classList.remove('is-hidden');
            overlay.classList.remove('is-hidden');
            cameraLabel.textContent = 'Stop camera';
            cameraBtn.disabled = false;
            snapBtn.disabled = false;
            connect();
            timer = setInterval(sendFrame, 200);
        };
    }

    function stopCamera() {
        clearInterval(timer);
        timer = null;
        if (stream) stream.getTracks().forEach(function (t) { t.stop(); });
        stream = null;
        video.srcObject = null;
        video.classList.add('is-hidden');
        overlay.classList.add('is-hidden');
        placeholder.classList.remove('is-hidden');
        ctx.clearRect(0, 0, overlay.width, overlay.height);
        cameraLabel.textContent = 'Start camera';
        snapBtn.disabled = true;
        setStatus('Camera stopped.');
    }

    function sendFrame() {
        if (waiting || !socket || !socket.connected) return;
        waiting = true;
        setTimeout(function () { waiting = false; }, 2000); // never stall
        hCtx.drawImage(video, 0, 0, hidden.width, hidden.height);
        socket.emit('process_frame', { image: hidden.toDataURL('image/jpeg', 0.6) });
    }

    function onResults(data) {
        waiting = false;
        if (!data || !Array.isArray(data.faces)) return;
        drawOverlay(data.faces);
        updateBars(data.global_emotions || {});
        document.getElementById('face-count').textContent = String(data.faces.length);
        if (data.faces.length > 0) {
            var face = data.faces[0];
            document.getElementById('dominant').textContent = face.emotion;
            document.getElementById('confidence').textContent = face.confidence.toFixed(0) + '%';
            document.getElementById('intensity').textContent = face.analysis.intensity;
            document.getElementById('insight').textContent = face.analysis.insight + '.';
        } else {
            document.getElementById('dominant').textContent = '–';
            document.getElementById('confidence').textContent = '–';
            document.getElementById('intensity').textContent = '–';
            document.getElementById('insight').textContent = 'No face found. Face the camera in good light.';
        }
    }

    function drawOverlay(faces) {
        ctx.clearRect(0, 0, overlay.width, overlay.height);
        var sx = overlay.width / hidden.width;
        var sy = overlay.height / hidden.height;
        faces.forEach(function (face) {
            var x = face.box[0] * sx, y = face.box[1] * sy, w = face.box[2] * sx, h = face.box[3] * sy;
            ctx.strokeStyle = '#ffffff';
            ctx.lineWidth = 4;
            ctx.strokeRect(x, y, w, h);
            var labelY = Math.max(0, y - 44);
            ctx.fillStyle = '#3730a3';
            ctx.fillRect(x, labelY, Math.max(w, 160), 44);
            ctx.fillStyle = '#ffffff';
            ctx.font = '600 20px Inter, system-ui, sans-serif';
            ctx.fillText(face.emotion + ' ' + face.confidence.toFixed(0) + '%', x + 10, labelY + 29);
        });
    }

    function updateBars(values) {
        EMOTIONS.forEach(function (name) {
            var v = Number(values[name]) || 0;
            document.getElementById('bar-' + name).style.width = v.toFixed(1) + '%';
            document.getElementById('val-' + name).textContent = v.toFixed(1) + '%';
            document.getElementById('track-' + name).setAttribute('aria-valuenow', v.toFixed(0));
        });
    }

    async function saveSnapshot() {
        snapBtn.disabled = true;
        hCtx.drawImage(video, 0, 0, hidden.width, hidden.height);
        try {
            var res = await fetch('/capture', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken },
                credentials: 'same-origin',
                body: JSON.stringify({ image: hidden.toDataURL('image/jpeg', 0.85) })
            });
            var body = {};
            try { body = await res.json(); } catch (e) { /* non-JSON error page */ }
            if (res.ok) setStatus((body.message || 'Snapshot saved.') + ' View it on your Account page.', 'ok');
            else if (res.status === 429) setStatus('Too many snapshots. Wait a minute and try again.', 'err');
            else setStatus(body.error || 'Snapshot could not be saved. Please try again.', 'err');
        } catch (e) {
            setStatus('Snapshot could not be saved. Check your connection.', 'err');
        }
        snapBtn.disabled = !stream;
    }

    cameraBtn.addEventListener('click', function () { if (stream) stopCamera(); else startCamera(); });
    snapBtn.addEventListener('click', saveSnapshot);
    window.addEventListener('pagehide', function () { if (stream) stopCamera(); });
})();
