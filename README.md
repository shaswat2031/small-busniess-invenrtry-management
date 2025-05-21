[![MIT License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![GitHub Repo](https://img.shields.io/badge/GitHub-View%20on%20GitHub-blue?logo=github)](https://github.com/shaswat2031/small-busniess-invenrtry-management)

# Small Business Inventory Management

A modern, full-featured inventory management system for small businesses. Manage products, sales, team members, and analytics with a beautiful, responsive dashboard and robust role-based access control.

---

## 🌟 Live Demo & Screenshots
- **GitHub Repository:** [https://github.com/shaswat2031/small-busniess-invenrtry-management](https://github.com/shaswat2031/small-busniess-invenrtry-management)
- *(Add your live demo link here if deployed)*

<!--
![Dashboard Screenshot](static/screenshots/dashboard.png)
![Product Management](static/screenshots/products.png)
-->

---

## 🚀 Features
- **Product Management:** Add, edit, delete, and track products with low stock alerts and barcode support.
- **Sales & Billing:** Record sales, generate bills, and view sales history with export options.
- **Team Management:** Invite team members, assign roles (Staff, Manager, Admin), and set granular permissions.
- **Analytics & Reports:** Visualize sales, inventory trends, and download detailed reports.
- **Authentication:** Secure login, registration, password reset, and email verification.
- **Responsive UI:** Modern design using Tailwind CSS, mobile-friendly and fast.
- **Role-Based Access:** Fine-grained access control for different user types.
- **Notifications:** Flash messages for actions, low stock, and important events.
- **Security:** Passwords hashed with bcrypt, session management with Flask-Login.
- **Extensible:** Easily customizable for your business needs.

---

## 🛠️ Tech Stack
- **Backend:** Python 3.10+, Flask, Flask-Login, Flask-Bcrypt, Flask-PyMongo
- **Database:** MongoDB (local or cloud)
- **Frontend:** Jinja2 templates, Tailwind CSS, FontAwesome
- **Other:** ReportLab (PDF reports), Flask-Mail (email), Vercel (optional deployment)

---

## ⚡ Quick Start

### 1. Clone the Repository
```
git clone <repo-url>
cd "Proejcts + DSa ( 2025)/small-busniess-invenrtry-management"
```

### 2. Create and Activate a Virtual Environment
```
python -m venv venv
venv\Scripts\activate
```

### 3. Install Dependencies
```
pip install -r requirements.txt
```

### 4. Configure Environment
- Edit `config.py`:
  - Set your `MONGO_URI` (local or Atlas cluster)
  - Set `SECRET_KEY` and email credentials for password reset
- Ensure MongoDB is running and accessible

### 5. Run the Application
```
python app.py
```
- Visit [http://127.0.0.1:5000](http://127.0.0.1:5000)

---

## 🏗️ Project Structure
```
small-busniess-invenrtry-management/
│   app.py                # Main Flask app
│   config.py             # Configuration
│   requirements.txt      # Python dependencies
│   README.md             # Project documentation
│   app.log               # Application logs
│   static/               # CSS, JS, images
│   templates/            # Jinja2 HTML templates
│   ...
```

---

## 👤 User Roles & Permissions
- **Staff:** View and sell products
- **Manager:** Staff permissions + add/edit products, view reports
- **Admin:** All permissions + manage team members

---

## 🔒 Security Best Practices
- Passwords are hashed using bcrypt
- Sessions managed with Flask-Login
- CSRF protection via Flask forms (if enabled)
- Never expose your `SECRET_KEY` or database credentials
- For production, use HTTPS and a production-ready WSGI server (e.g., Gunicorn)

---

## 🌐 Deployment
- **Local:** Run with Flask’s built-in server for development
- **Production:**
  - Use Gunicorn or uWSGI behind Nginx/Apache
  - Set `debug=False` in `app.py`
  - Configure environment variables for secrets
- **Vercel:** Deploy with `vercel.json` (see file for config)

---

## 🛠️ Customization
- **Styling:** Edit `static/` or use Tailwind config for custom themes
- **Templates:** Modify or extend HTML in `templates/`
- **Business Logic:** Add new routes or features in `app.py`
- **Database:** Add new collections or fields as needed

---

## 🧩 Integrations
- **Email:** Configure SMTP in `config.py` for password reset and notifications
- **PDF Reports:** Uses ReportLab for generating downloadable sales reports
- **Analytics:** Built-in charts, can be extended with Chart.js or similar

---

## 🐞 Troubleshooting
- Check `app.log` for errors
- Ensure MongoDB is running and accessible
- Verify all environment variables are set in `config.py`
- For Windows, use `venv\Scripts\activate` to activate your virtual environment

---

## 🤝 Contributing
1. Fork the repository
2. Create a new branch (`git checkout -b feature/your-feature`)
3. Commit your changes (`git commit -am 'Add new feature'`)
4. Push to the branch (`git push origin feature/your-feature`)
5. Open a Pull Request

---

## 📄 License
MIT License — free for personal and commercial use.

---

## 💬 Support
For questions, feature requests, or bug reports, please open an issue or contact the maintainer.

---

## ❓ FAQ

**Q: Can I deploy this on shared hosting or cloud platforms?**  
A: Yes! You can deploy on any platform that supports Python and MongoDB. For production, use Gunicorn or uWSGI behind Nginx/Apache.

**Q: How do I add more features or change the UI?**  
A: Edit the Python code in `app.py` for backend logic, and modify HTML/CSS in `templates/` and `static/` for the frontend.

**Q: Is this project open source?**  
A: Yes, it's licensed under MIT. Contributions are welcome!

**Q: Where can I get help?**  
A: Open an issue on the [GitHub repo](https://github.com/shaswat2031/small-busniess-invenrtry-management) or contact the maintainer directly.
