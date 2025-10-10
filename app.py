import csv
from io import StringIO
import os
from flask import Flask, Response, flash, json, jsonify, render_template, request, redirect, session, url_for
from flask_mail import Mail, Message
import sqlite3
from datetime import datetime, timedelta
from collections import Counter
from dotenv import load_dotenv

app = Flask(__name__)
app.secret_key = "ILoveDucks"

load_dotenv()  # load environment variables

DATE_FORMAT = "%d/%m/%Y"
# default updates seperator between status and date
UPDATES_SEPERATOR = " - "
# number of days passed to consider no response
NO_RESPONSE_DAYS = 14
# auto no response status
AUTO_NO_RESPONSE = True

# configure Flask-Mail
app.config["MAIL_SERVER"] = "smtp.gmail.com"
app.config["MAIL_PORT"] = 465
app.config["MAIL_USE_TLS"] = False
app.config["MAIL_USE_SSL"] = True
app.config["MAIL_USERNAME"] = os.getenv('MAIL_USERNAME')
app.config["MAIL_PASSWORD"] = os.getenv('MAIL_PASSWORD')    # no hacking!
app.config["MAIL_DEFAULT_SENDER"] = os.getenv("MAIL_USERNAME")
mail = Mail(app)

# connect to databases file
def get_conn():
    return sqlite3.connect("databases.db")

# initialize database if doesn't exist
def init_db():
    with get_conn() as conn:
        cur = conn.cursor()
        # users table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password TEXT NOT NULL
            )
        """)

        # applications table
        cur.execute("""
            CREATE TABLE IF NOT EXISTS applications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                company TEXT NOT NULL,
                role TEXT NOT NULL,
                status TEXT NOT NULL,
                updates TEXT,
                notes TEXT,
                user_id INTEGER,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        """)

        conn.commit()

# initialize database before first request
init_db()

# receive user settings from cookies
def get_user_settings():
    # default settings
    auto_no_response = AUTO_NO_RESPONSE
    no_response_days = NO_RESPONSE_DAYS

    # auto 'no response'
    auto_nr = request.cookies.get("autoNoResponse")
    if auto_nr:
        auto_no_response = (auto_nr.lower() == "true")

    # days until auto 'no response'
    no_resp_days = request.cookies.get("noResponseDays")
    try:
        no_response_days = int(no_resp_days)
    except (TypeError, ValueError):
        # keep default if missing or invalid
        pass

    # inactive at bottom
    inactive_bottom = request.cookies.get("inactiveBottom")
    if inactive_bottom:
        inactive_bottom = (inactive_bottom.lower() == "true")

    # email on auto 'no response'
    email_no_response = request.cookies.get("emailNoResponse")
    email_address = request.cookies.get("emailAddress")

    return auto_no_response, no_response_days, inactive_bottom, email_no_response, email_address

# parse dates
def parse_date(date_str, as_datetime=True):
    """Parse a date string in various formats.
    Returns datetime by default, or formatted string if as_datetime=False."""
    for fmt in (
        "%d-%m-%Y", "%Y-%m-%d",
        "%d/%m/%Y", "%Y/%m/%d",
        "%d.%m.%Y", "%Y.%m.%d",
        "%d %m %Y", "%Y %m %d",
        "%d%m%Y", "%Y%m%d"
    ):
        try:
            dt = datetime.strptime(date_str, fmt)
            return dt if as_datetime else dt.strftime(DATE_FORMAT)
        except (ValueError, TypeError):
            continue
    # fallback to today's date
    dt = datetime.now()
    return dt if as_datetime else dt.strftime(DATE_FORMAT)

# auto update no response
def update_no_response(applications, no_response_days, email_no_response=None, email_address=None):
    today = datetime.now()
    with get_conn() as conn:
        cur = conn.cursor()
        for app in applications:
            updates = app["updates"].split("\n")
            if updates:
                last_update = updates[-1]
                try:
                    last_date_str = last_update.split(UPDATES_SEPERATOR)[1]
                    last_date = parse_date(last_date_str)
                    days_diff = (today - last_date).days
                    if days_diff > no_response_days and not last_update.startswith("No Response"):
                        # append No Response update
                        new_update = f"No Response{UPDATES_SEPERATOR}{today.strftime(DATE_FORMAT)}"
                        new_updates_text = app["updates"].strip() + "\n" + new_update
                        # update in database
                        cur.execute("UPDATE applications SET status = ?, updates = ? WHERE id = ?", 
                                    ("No Response", new_updates_text, app["id"]))
                        conn.commit()

                        # send email
                        if email_no_response == "true" and email_address:
                            # --- email does not work with Render ---
                            pass
                            # subject = f"Job Tracker Update"
                            # body_html = f"""
                            #     <p>Hello, your application to <strong>{app['company']}</strong> for the role of <strong>{app['role']}</strong>
                            #     has been marked as 'No Response' after {days_diff} days without updates.</p>

                            #     <hr>
                            #     <p style="font-family: monospace; font-size: 1.2em; color: #555;">
                            #     This is an automated message from the "Job Tracker" app,
                            #     made by <a href="https://www.linkedin.com/in/ido-hassidim-12705125b/" target="_blank">Ido Hassidim</a>
                            #     </p>
                            #     """
                            # try:
                            #     msg = Message(subject, recipients=[email_address], html=body_html)
                            #     mail.send(msg)
                            # except Exception as e:
                            #     print(f"Error sending email: {e}")

                except (IndexError, ValueError):
                    continue

# data for pie chart
def get_chart1_data(applications):
    status_data = Counter(app["status"] for app in applications)
    return status_data

# data for bar chart
def get_chart2_data(applications):
    # extract 'applied' dates from updates (bar chart)
    applied_dates = []
    for app in applications:
        updates = app["updates"].split("\n")
        for upd in updates:
            if upd.startswith("Applied - "):
                date_str = upd.split(" - ")[1]
                applied_dates.append(parse_date(date_str))
                break  # only the first "Applied" entry is needed

    # count applications per week
    week_counts = Counter()
    for date in applied_dates:
        days_to_sunday = (date.weekday() + 1) % 7
        week_start = date - timedelta(days=days_to_sunday)
        week_str = week_start.strftime("%d-%m-%Y")
        week_counts[week_str] += 1

    # sort by ascending week dates
    week_counts = dict(sorted(week_counts.items(), key=lambda x: parse_date(x[0])))

    # each week label and amount of applications in it
    week_labels = []
    week_values = []
    for i, (week_str, count) in enumerate(week_counts.items(), start=1):
        week_labels.append(f"Week {i}")
        week_values.append(count)
    # week date ranges
    week_ranges = []
    for week_str in week_counts.keys():
        week_start = parse_date(week_str)
        week_end = week_start + timedelta(days=6)
        week_ranges.append(f"{week_start.strftime('%d/%m')} → {week_end.strftime('%d/%m')}")

    # combine all data into a single list
    week_data = list(zip(week_labels, week_values, week_ranges))
    return week_data

# total amount of applications
def total_applications(applications):
    return len(applications)

# applications in process (non-rejected/no response)
def apps_in_process(applications):
    count = 0
    for app in applications:
        updates = app["updates"].split("\n")
        for upd in updates:
            if upd.startswith("Rejected") or upd.startswith("No Response"):
                count += 1
                break
    
    num_in_proc = len(applications) - count
    return num_in_proc

# average time to first response
def avg_first_response_time(applications):
    diffs = []
    for app in applications:
        # skip if no updates
        if not app["updates"]:
            continue

        lines = app["updates"].split("\n")
        # not enough info
        if len(lines) < 2:
            continue

        applied_line = lines[0]
        first_response_line = lines[1]

        # get as date object from updates
        applied_date = parse_date(applied_line.split(UPDATES_SEPERATOR)[1])
        first_response_date = parse_date(first_response_line.split(UPDATES_SEPERATOR)[1]) 
        diff_days = (first_response_date - applied_date).days   
        diffs.append(diff_days)

    if diffs:
        avg = sum(diffs) / len(diffs)
        # format nicely
        if avg % 1 == 0:
            avg_str = f"{int(avg)} days"
        else:
            avg_str = f"{round(avg, 1)} days"

        return avg_str

    else:
        return None

# rejection percentage
def rejection_percentage(applications):
    total_apps = len(applications)
    num_rej = 0
    for app in applications:
        status = app["status"].lower()
        if status in ["rejected", "no response"]:
            num_rej += 1

    # avoid division by zero
    rej_pct = (num_rej / total_apps * 100) if total_apps else 0

    # format nicely
    if rej_pct % 1 == 0:
        rej_pct_str = f"{int(rej_pct)}%"
    else:
        rej_pct_str = f"{round(rej_pct, 1)}%"

    return rej_pct_str
   

# homepage
@app.route("/") 
def home():
    # logged in user gets id
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    username = session.get("username")

    # get user settings from cookies
    auto_no_response, no_response_days, inactive_bottom, email_no_response, email_address = get_user_settings()

    if request.args.get("reset") == "1":
        return redirect(url_for("home"))
    else:
        # get filter, sort, order and search options from URL parameters
        status_filter = request.args.get("status_filter")   # filter by status
        sort = request.args.get("sort")                     # which column to sort by
        order = request.args.get("order")                   # asc or desc
        search = request.args.get("search")                 # search term

    applications = get_applications(user_id, status_filter, sort, order, search)

    # auto update no response statuses
    if auto_no_response:    # skip if disabled
        update_no_response(applications, no_response_days, email_no_response, email_address)

    # inactive at bottom
    if inactive_bottom:
        def inactive_key(app):
            inactive = app['status'].lower() in ['rejected', 'no response']
            return (inactive, -app['id'])  # active first, then by desc id
        
        applications.sort(key=inactive_key)

    # pie chart data
    status_data = get_chart1_data(applications)

    # bar chart data
    week_data = get_chart2_data(applications)

    stats = {
        "Total applications": total_applications(applications),
        "- In process": apps_in_process(applications),
        "- Rejected/No response": total_applications(applications) - apps_in_process(applications),
        "Avg. first response time": avg_first_response_time(applications),
        "Rejection rate": rejection_percentage(applications)
    }

    return render_template(
        "home.html", 
        applications=applications, 
        status_filter=status_filter,
        sort=sort,
        order=order,
        search=search,
        status_data=status_data,
        week_data=week_data,
        stats=stats,
        username=username
    )

# fetch all entries from database and apply filters, sorting, searching
def get_applications(user_id, status_filter=None, sort=None, order=None, search=None):
    with get_conn() as conn:
        cur = conn.cursor()

        valid_sort_cols = {"company", "role", "status"}
        valid_sort_orders = {"asc", "desc"}
        # default sorting
        sort_col = "id"
        sort_order = "desc"

        if sort in valid_sort_cols:
            sort_col = sort
        if order in valid_sort_orders:
            sort_order = order

        base_query = "SELECT id, company, role, status, updates, notes FROM applications"
        conditions = ["user_id = ?"]
        params = [user_id]

        if status_filter:
            # filter by status and sort by selected column
            conditions.append("status = ?")
            params.append(status_filter)

        if search:
            # search in company, role, or notes
            conditions.append("(company LIKE ? OR role LIKE ? OR notes LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%", f"%{search}%"])

        if conditions:
            # add WHERE if there are any conditions
            base_query += " WHERE " + " AND ".join(conditions)

        # add ORDER BY
        base_query += f" ORDER BY {sort_col} {sort_order}"

        cur.execute(base_query, params)
        rows = cur.fetchall()

        applications = [
            {
                "id": row[0], 
                "company": row[1],
                "role": row[2],
                "status": row[3],
                "updates": row[4],
                "notes": row[5]
            }
            for row in rows
        ]

        return applications
    
# fetch all entries from database, returns as list of dicts
def fetch_all_applications():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, company, role, status, updates, notes FROM applications")
        rows = cur.fetchall()

        applications = [
            {
                "id": row[0], 
                "company": row[1],
                "role": row[2],
                "status": row[3],
                "updates": row[4],
                "notes": row[5]
            }
            for row in rows
        ]

        return applications

# add new entry to database
@app.route("/add", methods=["POST"])
def add_application():
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]

    # get form data (html)
    company = request.form.get("company")
    role = request.form.get("role")
    date_applied = request.form.get("date_applied")
    
    if not date_applied:    # default to today if not provided
        date_applied = datetime.now().strftime(DATE_FORMAT)
    else:   # format date to default format
        date_applied = parse_date(date_applied, False)  # string format

    updates = f"Applied - {date_applied}"

    if company and role:
        with get_conn() as conn:
            cur = conn.cursor()
            cur.execute(
                "INSERT INTO applications (company, role, status, updates, notes, user_id) VALUES (?, ?, ?, ?, ?, ?)",
                (company, role, "Applied", updates, "", user_id)
            )
            conn.commit()
    return redirect(url_for("home"))

# delete entry from database
@app.route("/delete/<int:app_id>", methods=["POST"])
def delete_application(app_id):
    if "user_id" not in session:
        return redirect("/login")
    
    user_id = session["user_id"]
    
    with get_conn() as conn:
        cur = conn.cursor()
        # ensure user can only delete their own entries (extra safe)
        cur.execute("DELETE FROM applications WHERE id = ? AND user_id = ?", (app_id, user_id))
        conn.commit()
    return redirect(url_for("home"))

# duplicate entry in database
@app.route("/duplicate/<int:app_id>", methods=["POST"])
def duplicate_application(app_id):
    with get_conn() as conn:
        cur = conn.cursor()
        # fetch the application to duplicate
        cur.execute("SELECT company, role, status, updates, notes FROM applications WHERE id = ?", (app_id,))
        row = cur.fetchone()
        if row:
            company, role, status, updates, notes = row
            # insert a new entry with the same data
            cur.execute(
                "INSERT INTO applications (company, role, status, updates, notes) VALUES (?, ?, ?, ?, ?)",
                (company, role, status, updates, notes)
            )
            conn.commit()
    return redirect(url_for("home"))

# update status of an entry
@app.route("/update/<int:app_id>", methods=["POST"])
def update_status(app_id):
    new_status = request.form.get("status")
    if new_status:
        with get_conn() as conn:
            cur = conn.cursor()
            # when status is updated, automatically append to updates
            # get current updates
            cur.execute("SELECT updates FROM applications WHERE id = ?", (app_id,))
            row = cur.fetchone()
            current_updates = row[0] if row and row[0] else ""
            # append new update
            new_update = f"{new_status} - {datetime.now().strftime(DATE_FORMAT)}"

            if current_updates.strip():
                new_updates_text = current_updates.strip() + "\n" + new_update
            else:
                new_updates_text = new_update

            # update both status and updates
            cur.execute("UPDATE applications SET status = ?, updates = ? WHERE id = ?", 
                        (new_status, new_updates_text, app_id))
            conn.commit()
    return redirect(url_for("home"))

# update notes of an entry
@app.route("/update_notes/<int:app_id>", methods=["POST"])
def update_notes(app_id):
    new_notes = request.form.get("notes")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE applications SET notes = ? WHERE id = ?", (new_notes, app_id))
        conn.commit()
    return redirect(url_for("home"))

# update updates of an entry
@app.route("/update_updates/<int:app_id>", methods=["POST"])
def update_updates(app_id):
    new_updates = request.form.get("updates")
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("UPDATE applications SET updates = ? WHERE id = ?", (new_updates, app_id))
        conn.commit()
    return redirect(url_for("home"))

# backup database
@app.route("/backup")
def backup():
    applications = fetch_all_applications()
    json_data = json.dumps(applications, indent=4)
    return Response(
        json_data, 
        mimetype="application/json",
        headers={"Content-Disposition": "attachment; filename=applications_backup.json"}
    )

# export database to CSV
@app.route("/export_csv")
def export_csv():
    applications = fetch_all_applications()
    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["ID", "Company", "Role", "Status", "Updates", "Notes"])

    for app in applications:
        updates_txt = app.get("updates", "")
        notes_txt = app.get("notes", "")

        writer.writerow([
            app["id"],
            app["company"],
            app["role"],
            app["status"],
            updates_txt,
            notes_txt
        ])

    output.seek(0)
    return Response(
        output,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment;filename=applications.csv"}
    )

# restore database from backup
@app.route("/merge_restore", methods=["POST"])
def merge_restore():
    file = request.files['file']
    data = json.load(file)  # list of dicts with original ids
    mode = request.form.get("mode")  # 'restore' or 'merge'

    def get_apply_date(app_dict):
                updates = app_dict.get("updates", "")
                applied_line = updates.split("\n")[0] if updates else ""
                if applied_line not in ("", None) and UPDATES_SEPERATOR in applied_line:
                    date_str = applied_line.split(UPDATES_SEPERATOR)[1]
                    date = parse_date(date_str)
                    return date
                else:
                    return datetime.min  # treat missing dates as very old

    with get_conn() as conn:
        cur = conn.cursor()

        if mode == "restore":
            # WARNING: wipe current data
            cur.execute("DELETE FROM applications")
            conn.commit()

            data_sorted = sorted(data, key=get_apply_date, reverse=True)  # newest first

            for app in data_sorted:
                cur.execute(
                    """
                    INSERT INTO applications (id, company, role, status, updates, notes)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (app["id"], app["company"], app["role"], app["status"], 
                     app.get("updates", ""), app.get("notes", ""))
                )
            conn.commit()

        elif mode == "merge":
            # fetch existing applications
            cur.execute("SELECT * FROM applications")
            existing_apps = [dict(zip([col[0] for col in cur.description], row)) for row in cur.fetchall()]

            # combine existing + new entries
            combined_apps = existing_apps + data

            # sort combined list by apply date descending
            combined_sorted = sorted(combined_apps, key=get_apply_date, reverse=True)

            # clear DB and insert combined sorted list
            cur.execute("DELETE FROM applications")
            conn.commit()

            for app in combined_sorted:
                # handle ID conflicts by letting SQLite assign a new ID
                cur.execute("SELECT id FROM applications WHERE id=?", (app["id"],))
                if cur.fetchone():
                    cur.execute(
                        """
                        INSERT INTO applications (company, role, status, updates, notes)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (app["company"], app["role"], app["status"], 
                         app.get("updates", ""), app.get("notes", ""))
                    )
                else:
                    cur.execute(
                        """
                        INSERT INTO applications (id, company, role, status, updates, notes)
                        VALUES (?, ?, ?, ?, ?, ?)
                        """,
                        (app["id"], app["company"], app["role"], app["status"], 
                         app.get("updates", ""), app.get("notes", ""))
                    )
            conn.commit()

    return redirect(url_for("home"))


@app.route("/register", methods=["GET", "POST"])
def register():
    # user submitted registration form (POST)
    if (request.method == "POST"):
        username = request.form["username"]
        password = request.form["password"]
        confirm_password = request.form["confirm_password"]

        if password != confirm_password:
            # does not delete entered data
            return render_template(
                "register.html",
                error="Passwords do not match",
                username=username,
                password=password,
                confirm_password=confirm_password
            )

        with get_conn() as conn:
            cur = conn.cursor()
            try:
                cur.execute("INSERT into users (username, password) VALUES (?, ?)", (username, password))
                conn.commit()
                # store user id in session
                session["user_id"] = cur.lastrowid
                session["username"] = username
                return redirect(url_for("home"))
            except sqlite3.IntegrityError:
                return render_template("register.html", error="Username taken")
    # user opens registeration page (GET) 
    else:
        return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    # user submitted login form (POST)
    if (request.method == "POST"):
        username = request.form["username"]
        password = request.form["password"]

        with get_conn() as conn:
            cur = conn.cursor()
            # filter users.db to find if user exists
            cur.execute("SELECT id FROM users where username = ? AND password = ?", (username, password))
            user_data = cur.fetchone()
            
            if (user_data):
                # user exists
                session["user_id"] = user_data[0]   # id from users
                session["username"] = username
                return redirect(url_for("home"))
            else:
                # user doesn't exist or wrong password
                return render_template("login.html", error="Invalid username or password")
    # user opens login page (GET)
    else:
        return render_template("login.html")
    

@app.route("/logout")
def logout():
    session.clear() # remove user_id, username, etc.
    return redirect(url_for("login"))