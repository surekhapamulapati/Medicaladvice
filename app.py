from flask import Flask, render_template, request, redirect, url_for, session, flash
from pymongo import MongoClient
from bson.objectid import ObjectId
from dotenv import load_dotenv
import os
import pandas as pd
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import pytz
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from twilio.rest import Client
import requests

# ================= LOAD ENV =================
load_dotenv()

SECRET_KEY = os.getenv("SECRET_KEY")
MONGO_URI = os.getenv("MONGO_URI")

EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

TWILIO_ACCOUNT_SID = os.getenv("TWILIO_ACCOUNT_SID")
TWILIO_AUTH_TOKEN = os.getenv("TWILIO_AUTH_TOKEN")
TWILIO_PHONE_NUMBER = os.getenv("TWILIO_PHONE_NUMBER")

HF_API_KEY = os.getenv("HF_API_KEY")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

print("EMAIL:", EMAIL_ADDRESS)
print("PASSWORD:", EMAIL_PASSWORD)
print("PASSWORD LENGTH:", len(EMAIL_PASSWORD) if EMAIL_PASSWORD else "None")

app = Flask(__name__)
app.secret_key = SECRET_KEY

# ================= DATABASE =================
client = MongoClient(MONGO_URI)
db = client["medvice_db"]

users_collection = db["users"]
results_collection = db["diagnosis_results"]
contacts_collection = db["contacts"]

# ================= TIME =================
def get_indian_time():
    india = pytz.timezone("Asia/Kolkata")
    return datetime.now(india)

# ================= EMAIL =================
def send_email(to_email, subject, body):
    try:
        msg = MIMEMultipart()
        msg["From"] = EMAIL_ADDRESS
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        server = smtplib.SMTP("smtp.gmail.com", 587)
        server.ehlo()
        server.starttls()
        server.ehlo()

        server.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()

        print("✅ Email sent successfully")
        return True

    except Exception as e:
        print("❌ Email Error:", str(e))
        return False

# ================= SMS =================
def send_sms(to_number, message):
    try:
        if not to_number.startswith("+"):
            to_number = "+91" + to_number

        client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)

        client.messages.create(
            body=message,
            from_=TWILIO_PHONE_NUMBER,
            to=to_number
        )

        print("✅ SMS sent")
        return True
    except Exception as e:
        print("❌ SMS Error:", e)
        return False

# ================= HUGGINGFACE =================
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

import json
import re

def call_ai(symptoms_input):
    try:
        API_URL = "https://openrouter.ai/api/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": "http://localhost:5000",
            "X-Title": "MedVice AI"
        }

        payload = {
            "model": "mistralai/mistral-7b-instruct",
            "messages": [
                {
                    "role": "system",
                    "content": "You are a medical assistant. Respond ONLY in valid JSON."
                },
                {
                    "role": "user",
                    "content": f"""
User symptoms: {symptoms_input}

Respond ONLY in this JSON format:

{{
  "disease": "",
  "explanation": "",
  "medications": [],
  "precautions": [],
  "diet": [],
  "workout": []
}}

Do not add markdown.
Do not add text outside JSON.
Return only JSON.
"""
                }
            ],
            "temperature": 0.2
        }

        response = requests.post(API_URL, headers=headers, json=payload, timeout=60)

        if response.status_code != 200:
            print("OpenRouter Error:", response.text)
            raise Exception("API Error")

        result = response.json()
        ai_text = result["choices"][0]["message"]["content"]

        print("AI RAW RESPONSE:", ai_text)

        # Extract JSON safely
        match = re.search(r"\{.*\}", ai_text, re.DOTALL)

        if not match:
            raise Exception("No valid JSON found in AI response")

        json_string = match.group(0)

        ai_data = json.loads(json_string)

        return {
            "prediction": ai_data.get("disease", "AI Suggestion"),
            "description": ai_data.get("explanation", ""),
            "medications": ai_data.get("medications", []),
            "diets": ai_data.get("diet", []),
            "workouts": ai_data.get("workout", []),
            "precautions": ai_data.get("precautions", []),
            "ai_powered": True,
            "matched_count": 0,
            "confidence": "N/A"
        }

    except Exception as e:
        print("❌ OpenRouter Error:", str(e))

        return {
            "prediction": "AI Service Error",
            "description": "AI service currently unavailable.",
            "medications": [],
            "diets": [],
            "workouts": [],
            "precautions": [],
            "ai_powered": True,
            "matched_count": 0,
            "confidence": "N/A"
        }

# ================= HYBRID DIAGNOSIS =================
def hybrid_diagnosis(symptoms_input):

    try:
        df = pd.read_csv("datasets/Training.csv")
        df.fillna(0, inplace=True)

        # Normalize dataset columns
        df.columns = df.columns.str.strip().str.lower()

        symptom_columns = df.columns[:-1]  # exclude prognosis column

        # Normalize user input
        user_symptoms = [
            s.strip().lower().replace(" ", "_")
            for s in symptoms_input.split(",")
            if s.strip()
        ]

        print("User Symptoms:", user_symptoms)

        # Match symptoms
        matched_symptoms = [
            s for s in user_symptoms if s in symptom_columns
        ]

        print("Matched Symptoms:", matched_symptoms)

        if matched_symptoms:

            df["match_count"] = df[matched_symptoms].sum(axis=1)

            best_match = df.sort_values(
                by="match_count",
                ascending=False
            ).iloc[0]

            match_count = int(best_match["match_count"])

            if match_count > 0:

                disease = best_match["prognosis"]

                # Confidence = matched dataset columns / user symptoms
                confidence = round(
                    (match_count / len(user_symptoms)) * 100,
                    2
                )

                return {
                    "prediction": disease.title(),
                    "description": f"Matched {match_count} symptom(s) from medical dataset.",
                    "medications": ["Consult doctor for prescription"],
                    "diets": ["Balanced nutritious diet"],
                    "workouts": ["Light physical activity"],
                    "precautions": ["Monitor symptoms carefully"],
                    "ai_powered": False,
                    "matched_count": match_count,
                    "confidence": f"{confidence}%"
                }

        print("⚠ No dataset match → Using AI")
        return call_ai(symptoms_input)

    except Exception as e:
        print("❌ Dataset Error:", e)
        return call_ai(symptoms_input)

# ================= ROUTES =================
@app.route("/")
def root():
    return render_template("loading.html")

@app.route("/home")
def home():
    return render_template("index.html")

@app.route("/about")
def about():
    return render_template("about.html")

@app.route("/services")
def services():
    return render_template("services.html")

@app.route("/map")
def map():
    return render_template("map.html")

# ================= REGISTER =================
# ================= REGISTER =================
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":

        if users_collection.find_one({"username": request.form["username"]}):
            flash("Username already exists!", "error")
            return redirect(url_for("register"))

        users_collection.insert_one({
            "full_name": request.form["full_name"],
            "email": request.form["email"],
            "phone": request.form["phone"],
            "username": request.form["username"],
            "password": generate_password_hash(request.form["password"]),
            "created_at": get_indian_time()
        })

        flash("Registration successful! Please login.", "success")
        return redirect(url_for("login"))

    return render_template("register.html")

# ================= LOGIN =================
# ================= LOGIN =================
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":

        username = request.form.get("username")
        password = request.form.get("password")

        user = users_collection.find_one({"username": username})

        if not user:
            flash("User not found!", "error")
            return redirect(url_for("login"))

        if not check_password_hash(user["password"], password):
            flash("Incorrect password!", "error")
            return redirect(url_for("login"))

        # Successful login
        session["user_id"] = str(user["_id"])
        session["full_name"] = user["full_name"]

        flash(f"Welcome back, {user['full_name']}!", "success")
        return redirect(url_for("symptoms"))

    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    flash("You have been logged out successfully.", "success")
    return redirect(url_for("home"))


# ================= NEARBY HOSPITALS =================
@app.route("/appointment")
def appointment():

    # Optional: restrict access only after login
    if "user_id" not in session:
        flash("Please login to view nearby hospitals.")
        return redirect(url_for("login"))

    return render_template("appointment.html")


# ================= SYMPTOMS =================
@app.route("/symptoms", methods=["GET", "POST"])
def symptoms():

    if request.method == "POST":
        symptoms_input = request.form.get("symptoms")

        if not symptoms_input:
            flash("Please enter symptoms", "error")
            return redirect(url_for("symptoms"))

        session["symptoms_input"] = symptoms_input
        return redirect(url_for("results"))

    try:
        df = pd.read_csv("datasets/Training.csv")
        df.columns = df.columns.str.strip()
        all_symptoms = [
            col.replace("_", " ").title()
            for col in df.columns[:-1]
        ]
    except:
        all_symptoms = []

    return render_template("symptoms.html", all_symptoms=all_symptoms)

# ================= RESULTS =================
@app.route("/results")
def results():

    symptoms_input = session.get("symptoms_input", "")
    if not symptoms_input:
        return redirect(url_for("symptoms"))

    symptoms = [
        s.strip().lower().replace(" ", "_")
        for s in symptoms_input.split(",")
        if s.strip()
    ]

    try:
        training_df = pd.read_csv("datasets/Training.csv")
        training_df.fillna(0, inplace=True)

        # Normalize column names
        training_df.columns = training_df.columns.str.strip().str.lower()

        all_symptoms = training_df.columns[:-1]

        # Find matched symptoms
        matched_symptoms = [s for s in symptoms if s in all_symptoms]

        print("User Symptoms:", symptoms)
        print("Matched Symptoms:", matched_symptoms)

        # ---------------------------
        # 🔥 LOGIC YOU WANT
        # ---------------------------
        # If NO matched symptoms → use AI
        if len(matched_symptoms) == 0:
            print("⚠ No dataset match → Using AI")
            return render_ai_result(symptoms_input)

        # If matched → use dataset
        training_df["match_count"] = training_df[matched_symptoms].sum(axis=1)
        best_match = training_df.sort_values(
            by="match_count", ascending=False
        ).iloc[0]

        # If somehow match_count = 0 → fallback AI
        if best_match["match_count"] == 0:
            print("⚠ Match count zero → Using AI")
            return render_ai_result(symptoms_input)

        predicted_disease = best_match["prognosis"].strip().lower()

        # Load other datasets
        description_df = pd.read_csv("datasets/description.csv")
        medication_df = pd.read_csv("datasets/medications.csv")
        diet_df = pd.read_csv("datasets/diets.csv")
        workout_df = pd.read_csv("datasets/workout_df.csv")
        precautions_df = pd.read_csv("datasets/precautions_df.csv")

        def get_info(df):
            match = df[df["Disease"].str.strip().str.lower() == predicted_disease]
            if match.empty:
                return ["No data available"]
            values = match.drop(columns=["Disease"]).values.flatten().tolist()
            return [
                str(v).strip()
                for v in values
                if str(v).strip() and not str(v).isdigit()
            ]

        desc_row = description_df[
            description_df["Disease"].str.strip().str.lower() == predicted_disease
        ]
        description = (
            desc_row["Description"].values[0]
            if not desc_row.empty
            else "Description not available."
        )

        medications = get_info(medication_df)
        diets = get_info(diet_df)
        workouts = get_info(workout_df)
        precautions = get_info(precautions_df)

        return render_template(
            "results.html",
            prediction=predicted_disease.title(),
            description=description,
            medications=medications,
            diets=diets,
            workouts=workouts,
            precautions=precautions,
            ai_powered=False
        )

    except Exception as e:
        print("Dataset Error:", e)
        return render_ai_result(symptoms_input)

def render_ai_result(symptoms_input):

    ai_result = call_ai(symptoms_input)

    return render_template(
        "results.html",
        prediction=ai_result["prediction"],
        description=ai_result["description"],
        medications=ai_result["medications"],
        diets=ai_result["diets"],
        workouts=ai_result["workouts"],
        precautions=ai_result["precautions"],
        ai_powered=True
    )


# ================= SAVE RESULTS =================
# ================= SAVE RESULTS =================
@app.route("/save_results", methods=["POST"])
def save_results():

    if "user_id" not in session:
        flash("Please login first.", "error")
        return redirect(url_for("login"))

    try:
        user_id = ObjectId(session["user_id"])

        prediction = request.form.get("prediction")
        description = request.form.get("description")

        medications = request.form.getlist("medications")
        precautions = request.form.getlist("precautions")
        diets = request.form.getlist("diets")
        workouts = request.form.getlist("workouts")

        timestamp = get_indian_time()

        # Save to MongoDB
        results_collection.insert_one({
            "user_id": user_id,
            "prediction": prediction,
            "description": description,
            "medications": medications,
            "precautions": precautions,
            "diets": diets,
            "workouts": workouts,
            "timestamp": timestamp
        })

        user = users_collection.find_one({"_id": user_id})

        email_status = False
        sms_status = False

        if user:

            # Format lists nicely for email
            med_list = "\n".join([f"- {med}" for med in medications]) if medications else "N/A"
            pre_list = "\n".join([f"- {pre}" for pre in precautions]) if precautions else "N/A"
            diet_list = "\n".join([f"- {diet}" for diet in diets]) if diets else "N/A"
            work_list = "\n".join([f"- {work}" for work in workouts]) if workouts else "N/A"

            email_body = f"""
Hello {user['full_name']},

🩺 Your Diagnosis Report - MedVice
--------------------------------------------------

🧾 Prediction:
{prediction}

📖 Description:
{description}

💊 Medications:
{med_list}

⚠️ Precautions:
{pre_list}

🍎 Suggested Diet:
{diet_list}

🏃 Workout Recommendations:
{work_list}

📅 Saved On:
{timestamp.strftime("%d %b %Y, %I:%M %p")}

--------------------------------------------------

⚠️ Important:
This report is generated for informational purposes only.
Please consult a certified medical professional.

Stay healthy 💚
Team MedVice
"""

            # Send Email
            email_status = send_email(
                user["email"],
                f"🩺 MedVice Diagnosis Report - {prediction}",
                email_body
            )

            # Send Short SMS
            sms_message = f"MedVice: Diagnosis {prediction}. Check email for details."
            sms_status = send_sms(user["phone"], sms_message)

        # -------------------------------
        # SMART FLASH NOTIFICATIONS
        # -------------------------------
        if email_status and sms_status:
            flash("Diagnosis saved and report sent successfully!", "success")
        elif email_status:
            flash("Diagnosis saved. Email sent successfully!", "success")
        elif user:
            flash("Diagnosis saved, but notification sending failed.", "error")
        else:
            flash("Diagnosis saved successfully!", "success")

        return redirect(url_for("dashboard"))

    except Exception as e:
        print("❌ Save Results Error:", str(e))
        flash("Failed to save diagnosis. Please try again.", "error")
        return redirect(url_for("results"))

# ================= DASHBOARD =================
@app.route("/dashboard")
def dashboard():

    if "user_id" not in session:
        return redirect(url_for("login"))

    results = list(
        results_collection.find(
            {"user_id": ObjectId(session["user_id"])}
        ).sort("timestamp", -1)
    )

    india = pytz.timezone("Asia/Kolkata")

    for r in results:
        if "timestamp" in r:

            # Convert UTC → IST
            utc_time = r["timestamp"].replace(tzinfo=pytz.utc)
            ist_time = utc_time.astimezone(india)

            r["formatted_time"] = ist_time.strftime("%d %b %Y, %I:%M %p")

        # Avoid KeyError
        r.setdefault("medications", [])
        r.setdefault("precautions", [])
        r.setdefault("diets", [])
        r.setdefault("workouts", [])

    return render_template("dashboard.html", results=results)

# ================= CONTACT =================
@app.route("/contact", methods=["GET", "POST"])
def contact():

    if request.method == "POST":

        full_name = request.form.get("full_name")
        email = request.form.get("email")
        message = request.form.get("message")

        contacts_collection.insert_one({
            "full_name": full_name,
            "email": email,
            "message": message,
            "created_at": get_indian_time()
        })

        admin_body = f"""
New Contact Message

Name: {full_name}
Email: {email}

Message:
{message}
"""
        send_email(EMAIL_ADDRESS, "📩 New Contact Message - MedVice", admin_body)

        user_body = f"""
Hello {full_name},

We received your message. Our team will respond soon.

Thank you 💚
MedVice
"""
        send_email(email, "✅ Message Received - MedVice", user_body)

        flash("Message sent successfully!")
        return redirect(url_for("contact"))

    return render_template("contact.html")


if __name__ == "__main__":
    app.run(debug=True)
