<h1 align="center">😊 Decode Every Expression</h1>

<p align="center">
  A web app that watches your face through the webcam and tells you,<br>
  in real time, which of 7 emotions you're showing.
</p>

<p align="center">
  <img src="https://img.shields.io/badge/Python-3776AB?style=flat-square&logo=python&logoColor=white">
  <img src="https://img.shields.io/badge/TensorFlow-FF6F00?style=flat-square&logo=tensorflow&logoColor=white">
  <img src="https://img.shields.io/badge/OpenCV-5C3EE8?style=flat-square&logo=opencv&logoColor=white">
  <img src="https://img.shields.io/badge/Flask-000000?style=flat-square&logo=flask&logoColor=white">
  <img src="https://img.shields.io/badge/Docker-2496ED?style=flat-square&logo=docker&logoColor=white">
</p>

<!-- 📸 Add a screenshot or GIF of the dashboard detecting a face here -->

---

## ✨ Features

- 🎥 **Live webcam detection** — frames stream to the server over Socket.IO
- 🧠 **7 emotions** — Angry, Disgust, Fear, Happy, Sad, Surprise, Neutral, each with a confidence score
- 👥 **Works with more than one face** in the frame
- 💬 **Simple reading of the mood** — for example "User is pleasantly surprised" or "User is focused", plus an overall positive / negative / neutral label
- 📊 **Dashboard** showing the emotion scores
- 📸 **Snapshot capture** — save a frame with one click
- 🔑 **Login and register** pages

---

## 🧠 How it works

```text
 Browser webcam ──► frame sent over Socket.IO
                         │
                         ▼
              OpenCV finds faces (Haar cascade)
                         │
                         ▼
          Each face → grayscale, 64×64 → CNN model (Keras)
                         │
                         ▼
        7 emotion scores ──► top emotion + confidence + mood reading
                         │
                         ▼
               Results drawn live on the dashboard
```

---

## 🚀 Run it

### With Python

```bash
git clone https://github.com/madankumar16/decode-every-expression.git
cd decode-every-expression
pip install -r requirements.txt
cd face_emotion_detection/webapp
python app.py
```

Then open **http://localhost:7860** and allow camera access. (Set a `PORT` environment variable to use a different port.)

### With Docker

```bash
docker build -t decode-every-expression .
docker run -p 7860:7860 decode-every-expression
```

Open **http://localhost:7860**.

---

## 📁 Project layout

```text
face_emotion_detection/
├── src/
│   ├── emotion_model.h5                       ← trained emotion model
│   └── haarcascade_frontalface_default.xml    ← face detector
└── webapp/
    ├── app.py                                 ← Flask + Socket.IO server
    ├── templates/   (home, login, register, dashboard)
    └── static/css/
Dockerfile
requirements.txt
```

---

## 🛠️ Built with

Flask · Flask-SocketIO · OpenCV · TensorFlow / Keras · NumPy · Docker

---

## 🗺️ Next steps

- [ ] Load the Flask secret key from an environment variable
- [ ] Add real password checks and store accounts in a database
- [ ] Show emotion history over time on the dashboard

---

<p align="center">Made by <a href="https://github.com/madankumar16">Madan Kumar S</a> · ECE, VTU '28</p>
