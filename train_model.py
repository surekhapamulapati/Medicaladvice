# train_model.py
import pandas as pd
from sklearn.tree import DecisionTreeClassifier
import pickle

# Load your dataset
df = pd.read_csv('datasets/Training.csv')

# Features and target
X = df.drop('prognosis', axis=1)
y = df['prognosis']

# Train the model
model = DecisionTreeClassifier()
model.fit(X, y)

# Save the model
with open('model/disease_model.pkl', 'wb') as f:
    pickle.dump(model, f)
