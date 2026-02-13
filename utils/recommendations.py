import pandas as pd

# Load dataset
df = pd.read_csv('datasets/medical_data.csv')  # update if different path or format

def recommend_by_symptoms(symptoms):
    symptoms = symptoms.lower().split(",")  # Convert input to list
    matched_rows = []

    for _, row in df.iterrows():
        disease_symptoms = row['symptoms'].lower().split(",")
        if any(sym.strip() in disease_symptoms for sym in symptoms):
            matched_rows.append(row)

    return matched_rows[:5]  # Return top 5 matches
