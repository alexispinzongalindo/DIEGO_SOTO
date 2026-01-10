from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, IntegerField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Optional, Length, NumberRange


class MeetingForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    start_at = DateTimeLocalField('Start', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    end_at = DateTimeLocalField('End', format='%Y-%m-%dT%H:%M', validators=[Optional()])
    location = StringField('Location', validators=[Optional(), Length(max=200)])
    reminder_minutes = IntegerField('Reminder (minutes before)', validators=[Optional(), NumberRange(min=0, max=10080)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Meeting')
