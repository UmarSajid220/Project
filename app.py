from flask import Flask, render_template, request, redirect, session, url_for, jsonify

import sqlite3, datetime
import google.generativeai as genai
import os
import time
# Add dotenv to load .env
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
# IMPORTANT: The secret key should be stored securely and not hardcoded in a real application.
app.secret_key = "supersecret" 

# Configure Gemini API using an environment variable for security
# NOTE: You must set the GEMINI_API_KEY environment variable for the chatbot to work.

# Debug: Print the loaded API key (mask most of it for safety)
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
print(f"Loaded GEMINI_API_KEY: {GEMINI_API_KEY[:6]}...{GEMINI_API_KEY[-4:]}")
if GEMINI_API_KEY:
    genai.configure(api_key=GEMINI_API_KEY)
    print("genai.configure called with API key.")
else:
    print("GEMINI_API_KEY not found!")

# Use the correct model name
GEMINI_MODEL_NAME = "gemini-2.5-flash"

# ---------------- Database Setup ----------------
def get_db_connection():
    """Helper function to establish a database connection."""
    conn = sqlite3.connect("Database.db")
    conn.row_factory = sqlite3.Row # Allows accessing columns by name
    return conn

def init_db():
    """Initializes the database and tables if they don't exist."""
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Users table: simple passwordless authentication via username
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT UNIQUE,
                    role TEXT)""")
    
    # Tasks table
    cur.execute("""CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    employee TEXT,
                    title TEXT,
                    explanation TEXT,
                    priority TEXT,
                    deadline TEXT,
                    status TEXT DEFAULT 'Pending',
                    assigned_at TEXT)""")
    
    # Sessions table for login/logout tracking
    cur.execute("""CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    username TEXT,
                    login_time TEXT,
                    logout_time TEXT)""")
    conn.commit()
    conn.close()

init_db()

# ---------------- Utility Functions ----------------

def is_admin():
    """Checks if the current session user is an admin."""
    return "user" in session and session["role"] == "admin"

def is_employee():
    """Checks if the current session user is an employee."""
    return "user" in session and session["role"] == "employee"

# ---------------- Routes ----------------

@app.route('/')
def home():
    """Redirects authenticated users to their dashboard, otherwise to login."""
    if "user" in session:
        if session["role"] == "admin":
            return redirect(url_for('admin'))
        else:
            return redirect(url_for('employee'))
    return redirect(url_for('login'))

# -------- Signup ----------
@app.route("/signup", methods=["GET", "POST"])
def signup():
    """Allows new employees to sign up."""
    msg = ""
    if request.method == "POST":
        username = request.form["username"].strip()
        role = "employee"
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, role) VALUES (?,?)", (username, role))
            conn.commit()
            msg = f"Employee {username} signed up successfully! Please log in."
        except sqlite3.IntegrityError:
            msg = "Username already exists. Please choose a different one."
        except Exception as e:
            msg = f"An error occurred: {e}"
        finally:
            conn.close()
        return render_template("signup.html", message=msg)
    return render_template("signup.html")

@app.route("/admin_signup", methods=["GET", "POST"])
def admin_signup():
    """Allows the very first user to create an admin account for system bootstrap."""
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM users")
    user_count = cur.fetchone()[0]
    conn.close()
    
    if user_count > 1 and not is_admin():
         return redirect(url_for('login'))
     
     

    msg = "Create the initial Admin account." if user_count == 0 else "Admin account creation."
    
    if request.method == "POST":
        username = request.form["username"].strip()
        role = "admin"
        conn = get_db_connection()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (username, role) VALUES (?,?)", (username, role))
            conn.commit()
            msg = f"Admin account '{username}' created successfully! Please log in."
        except sqlite3.IntegrityError:
            msg = "Username already exists."
        finally:
            conn.close()
        return render_template("admin_signup.html", message=msg)
    return render_template("admin_signup.html", message=msg)

# -------- Login ----------
@app.route("/login", methods=["GET", "POST"])
def login():
    """Handles user login and session recording."""
    if request.method == "POST":
        username = request.form["username"].strip()
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT role FROM users WHERE username=?", (username,))
        data = cur.fetchone()
        conn.close()
        
        if data:
            role = data[0]
            session["user"] = username
            session["role"] = role

            # Record login
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute("INSERT INTO sessions (username, login_time) VALUES (?,?)",
                        (username, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
            conn.commit()
            conn.close()

            return redirect(url_for('admin') if role == "admin" else url_for('employee'))
        else:
            return render_template("login.html", message="User not found. Try signing up.")
    return render_template("login.html")

# -------- Logout ----------
@app.route("/logout")
def logout():
    """Handles user logout and updates the session end time."""
    if "user" in session:
        username = session["user"]
        conn = get_db_connection()
        cur = conn.cursor()
        # Find the latest session without logout_time
        cur.execute("""
            SELECT id FROM sessions
            WHERE username=? AND logout_time IS NULL
            ORDER BY login_time DESC LIMIT 1
        """, (username,))
        row = cur.fetchone()
        if row:
            cur.execute("UPDATE sessions SET logout_time=? WHERE id=?",
                        (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), row[0]))
            conn.commit()
        conn.close()
    session.clear()
    return redirect(url_for('login'))

# -------- Admin Dashboard ----------
@app.route("/admin")
def admin():
    """Admin dashboard to view all tasks and session logs."""
    if not is_admin():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    # Fetch tasks
    cur.execute("SELECT * FROM tasks ORDER BY status, deadline")
    tasks = cur.fetchall()
    # Fetch all users
    cur.execute("SELECT username FROM users WHERE role='employee'")
    employees = [row["username"] for row in cur.fetchall()]
    # Fetch session logs
    cur.execute("SELECT * FROM sessions ORDER BY login_time DESC")
    logs = cur.fetchall()
    conn.close()
    
    return render_template("admin_dashboard.html", tasks=tasks, logs=logs, employees=employees)

@app.route("/assign_task", methods=["GET", "POST"])
def assign_task():
    """Admin route to assign a new task."""
    if not is_admin():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT username FROM users WHERE role='employee'")
    employees = [row["username"] for row in cur.fetchall()]
    conn.close()
    
    if request.method == "POST":
        employee = request.form["employee"]
        title = request.form["title"]
        explanation = request.form["explanation"]
        priority = request.form["priority"]
        deadline = request.form["deadline"]
        assigned_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("INSERT INTO tasks (employee, title, explanation, priority, deadline, assigned_at) VALUES (?,?,?,?,?,?)",
                    (employee, title, explanation, priority, deadline, assigned_at))
        conn.commit()
        conn.close()
        return redirect(url_for('admin'))
        
    return render_template("assign_task.html", employees=employees)

# -------- Employee Dashboard ----------
@app.route("/employee")
def employee():
    """Employee dashboard to view assigned tasks and personal log history."""
    if not is_employee():
        return redirect(url_for('login'))
        
    username = session["user"]
    conn = get_db_connection()
    cur = conn.cursor()
    
    # Fetch tasks for the current employee
    cur.execute("SELECT * FROM tasks WHERE employee=? ORDER BY status DESC, priority DESC, deadline ASC", (username,))
    tasks = cur.fetchall()
    
    # Fetch personal login/logout logs
    cur.execute("SELECT login_time, logout_time FROM sessions WHERE username=? ORDER BY login_time DESC", (username,))
    logs = cur.fetchall()
    conn.close()
    
    return render_template("employee_dashboard.html", user=username, tasks=tasks, logs=logs)

@app.route("/complete_task/<int:task_id>")
def complete_task(task_id):
    """Allows an employee to mark a task as completed."""
    if not is_employee():
        return redirect(url_for('login'))
        
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("UPDATE tasks SET status='Completed' WHERE id=?", (task_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('employee'))

# -------- Chatbot Integration ----------
@app.route("/chat", methods=["GET"])
def chat_page():
    """Renders the chat interface."""
    if "user" not in session:
        return redirect(url_for('login'))
    return render_template("chat.html")

@app.route("/chatbot", methods=["POST"])
def chatbot():
    """Handles API call to the Gemini chatbot."""
    user_input = request.json.get("message")
    
    if not GEMINI_API_KEY:
        reply = "Gemini API key is not configured. Please set the GEMINI_API_KEY environment variable."
        return jsonify({"response": reply})
        
    try:
        # Use the correct GenerativeModel API for google-generativeai >=0.8.0
        model = genai.GenerativeModel(GEMINI_MODEL_NAME)
        response = model.generate_content(user_input)
        reply = response.text
    except Exception as e:
        print(f"Gemini API Error: {e}")
        reply = "Sorry, I am currently experiencing connection issues. Please try again later."
    return jsonify({"response": reply})

if __name__ == "__main__":
    # Remove debug=True for production environments
    print(f"Starting application. Gemini API Status: {'Configured' if GEMINI_API_KEY else 'NOT CONFIGURED'}")
    app.run(debug=True)
