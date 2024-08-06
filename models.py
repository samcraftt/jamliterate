from database import db


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    google_id = db.Column(db.String(100), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    study_sets = db.relationship('StudySet', backref='user', lazy=True)


class StudySet(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    cards = db.relationship('FlashCard', backref='study_set', lazy=True)


class FlashCard(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    question = db.Column(db.Text, nullable=False)
    answer = db.Column(db.Text, nullable=False)
    study_set_id = db.Column(db.Integer, db.ForeignKey('study_set.id'), nullable=False)
    starred = db.Column(db.Boolean, default=False)
