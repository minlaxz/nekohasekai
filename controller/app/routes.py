"""Application routes."""

from json import dump
from flask import current_app as app
from flask import make_response, render_template, request

from .add_client import Modifier
from .models import User, db


@app.route("/", methods=["GET", "POST"])
def root():
    if request.method == "POST":
        email = request.form.get("email")
        if email:
            existing_user = User.query.filter(User.email == email).first()
            if existing_user:
                return make_response(f"({email}) already exists!")
            else:
                modifier = Modifier()
                modifier.generate()
                new_user = User(
                    email=email, **modifier.user
                )  # Create an instance of the User class
                db.session.add(new_user)  # Adds new User record to database
                db.session.commit()  # Commits all changes
                modifier.add_client(**modifier.user)
                configs = modifier.generate_config()
                return make_response(
                    f"User {new_user.short_id} has been created. "
                    f"Here are the configs: {dump(configs)}"
                )
            # redirect(url_for("generate_configs"))
    return render_template("index.html", message=None, host=request.host_url)
