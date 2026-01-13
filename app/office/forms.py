from flask_wtf import FlaskForm
from wtforms import StringField, TextAreaField, SubmitField, IntegerField, SelectField
from wtforms.fields import DateTimeLocalField
from wtforms.validators import DataRequired, Optional, Length, NumberRange, Email


class MeetingForm(FlaskForm):
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    start_at = DateTimeLocalField('Start', format='%Y-%m-%dT%H:%M', validators=[DataRequired()])
    end_at = DateTimeLocalField('End', format='%Y-%m-%dT%H:%M', validators=[Optional()])
    location = StringField('Location', validators=[Optional(), Length(max=200)])
    reminder_minutes = IntegerField('Reminder (minutes before)', validators=[Optional(), NumberRange(min=0, max=10080)])
    notes = TextAreaField('Notes', validators=[Optional()])
    submit = SubmitField('Save Meeting')


class ProjectForm(FlaskForm):
    name = StringField('Project Name', validators=[DataRequired(), Length(max=120)])
    submit = SubmitField('Save Project')


class LibraryDocumentForm(FlaskForm):
    owner_id = SelectField('Owner', coerce=int, validators=[DataRequired()])
    category = SelectField('Category', choices=[('project', 'Project'), ('personal', 'Personal')], validators=[DataRequired()])
    project_id = SelectField('Project (if category is Project)', coerce=int, validators=[Optional()])
    title = StringField('Title', validators=[DataRequired(), Length(max=200)])
    description = TextAreaField('Description', validators=[Optional()])
    submit = SubmitField('Save Document')


class EmailLibraryDocumentForm(FlaskForm):
    to_email = StringField('To', validators=[DataRequired(), Email(), Length(max=120)])
    message = TextAreaField('Message', validators=[Optional()])
    submit = SubmitField('Send')


class DeleteForm(FlaskForm):
    submit = SubmitField('Delete')


class AdminSettingsForm(FlaskForm):
    show_marketing_landing = SelectField(
        'Public Marketing Landing Page',
        choices=[('off', 'Hide'), ('on', 'Show')],
        validators=[DataRequired()],
    )
    company_name = StringField('Company Name', validators=[Optional(), Length(max=120)])
    company_address = TextAreaField('Company Address', validators=[Optional()])
    company_phone = StringField('Company Phone', validators=[Optional(), Length(max=50)])
    company_fax = StringField('Company Fax', validators=[Optional(), Length(max=50)])
    company_email = StringField('Company Email', validators=[Optional(), Email(), Length(max=120)])
    company_logo_path = StringField('Company Logo Path', validators=[Optional(), Length(max=200)])
    submit = SubmitField('Save Settings')
