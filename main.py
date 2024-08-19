from flask import Flask, request, jsonify, session, render_template, redirect, url_for, send_from_directory, flash
from google.oauth2 import id_token
from google.auth.transport import requests as google_requests
from google_auth_oauthlib.flow import Flow
import os
import random
import openai
import json
from supabase import create_client, Client

client_secrets = json.loads(os.getenv("CLIENT_SECRETS_JSON"))

# Start up the app with Flask and SQLAlchemy
app = Flask(__name__)
app.secret_key = os.environ.get('FLASK_SECRET_KEY')
openai.api_key = os.environ.get('OPENAI_API_KEY')
GOOGLE_CLIENT_ID = os.environ.get('GOOGLE_CLIENT_ID')
GOOGLE_CLIENT_SECRET = os.environ.get('GOOGLE_CLIENT_SECRET')
GOOGLE_DISCOVERY_URL = "https://accounts.google.com/.well-known/openid-configuration"
supabase_url = os.environ.get("SUPABASE_URL")
supabase_key = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(supabase_url, supabase_key)

@app.route('/favicon.png')
def favicon():
    return send_from_directory(os.path.join(app.root_path), 'favicon.png', mimetype='image/png')

@app.route('/')
def home():
    user_id = session.get('user_id')
    if user_id:
        return redirect(url_for('dashboard'))
    return render_template('home.html')

@app.route('/login')
def login():
    flow = Flow.from_client_config(
        client_secrets,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile',
                'https://www.googleapis.com/auth/userinfo.email']
    )
    flow.redirect_uri = url_for('callback', _external=True)
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    session['state'] = state
    return redirect(authorization_url)

@app.route('/callback')
def callback():
    if 'state' not in session:
        return redirect(url_for('login'))
    flow = Flow.from_client_config(
        client_secrets,
        scopes=['openid', 'https://www.googleapis.com/auth/userinfo.profile',
                'https://www.googleapis.com/auth/userinfo.email'],
        state=session['state']
    )
    flow.redirect_uri = url_for('callback', _external=True)
    flow.fetch_token(authorization_response=request.url)
    credentials = flow.credentials
    id_info = id_token.verify_oauth2_token(
        id_token=credentials.id_token,
        request=google_requests.Request(),
        audience=GOOGLE_CLIENT_ID
    )
    response = supabase.table('users').select('*').eq('google_id', id_info['sub']).execute()
    user = response.data[0] if response.data else None
    if not user:
        user = {
            'google_id': id_info['sub'],
            'email': id_info['email'],
            'name': id_info['name']
        }
        response = supabase.table('users').insert(user).execute()
        user = response.data[0]
    session['user_id'] = user.id
    return redirect(url_for('dashboard'))

@app.route('/dashboard')
def dashboard():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    user_response = supabase.table('users').select('*').eq('id', user_id).execute()
    user = user_response.data[0] if user_response.data else None  
    study_sets_response = supabase.table('study_sets').select('*').eq('user_id', user_id).execute()
    study_sets = study_sets_response.data
    return render_template('dashboard.html', user=user, study_sets=study_sets)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    return redirect(url_for('home'))

@app.route('/create_jampack', methods=['GET', 'POST'])
def create_jampack():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    if request.method == 'POST':
        title = request.form.get('title')
        new_set = {
            'title': title,
            'user_id': user_id
        }        
        supabase.table('study_sets').insert(new_set).execute()
        return redirect(url_for('dashboard'))
    return render_template('create_jampack.html')

@app.route('/jampacks/<int:set_id>', methods=['GET', 'POST'])
def study_set(set_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    this_set_response = supabase.table('study_sets').select('*').eq('id', set_id).eq('user_id', user_id).execute()
    this_set = this_set_response.data[0] if this_set_response.data else None
    if not this_set:
        return jsonify({'error': 'Study set not found'}), 404
    if request.method == 'POST':
        if request.form.get('_method') == 'PUT':
            this_set['title'] = request.form.get('title', this_set['title'])
            supabase.table('study_sets').update(this_set).eq('id', set_id).execute()
        elif request.form.get('_method') == 'SHARE':
            recipient_email = request.form.get('email')
            recipient_response = supabase.table('users').select('*').eq('email', recipient_email).execute()
            recipient = recipient_response.data[0] if recipient_response.data else None
            if not recipient:
                flash('Recipient not found. Please check the email address and try again.', 'error')
                return redirect(url_for('study_set', set_id=set_id))
            sender_response = supabase.table('users').select('*').eq('id', user_id).execute()
            sender = sender_response.data[0] if sender_response.data else None
            title = this_set['title'] + ' (from ' + sender['name'] + ')'
            new_set = {
                'title': title,
                'user_id': recipient['id']
            }
            new_set_response = supabase.table('study_sets').insert(new_set).execute()
            new_set_id = new_set_response.data[0]['id']
            cards_response = supabase.table('flash_cards').select('*').eq('study_set_id', set_id).execute()
            cards = cards_response.data
            for card in cards:
                new_card = {
                    'question': card['question'],
                    'answer': card['answer'],
                    'study_set_id': new_set_id
                }
                supabase.table('flash_cards').insert(new_card).execute()
            flash('Jampack shared successfully.', 'success')
        elif request.form.get('_method') == 'DELETE':
            supabase.table('flash_cards').delete().eq('study_set_id', set_id).execute()
            supabase.table('study_sets').delete().eq('id', set_id).execute()
            return redirect(url_for('dashboard'))
    cards_response = supabase.table('flash_cards').select('*').eq('study_set_id', set_id).execute()
    cards = cards_response.data
    shuffle = request.args.get('shuffle', 'false').lower() == 'true'
    starred_only = request.args.get('starred_only', 'false').lower() == 'true'
    flip_cards = request.args.get('flip_cards', 'false').lower() == 'true'
    if starred_only:
        cards = [card for card in cards if card['starred']]
    if shuffle:
        cards = random.sample(cards, len(cards))
    return render_template('study_set.html', study_set=this_set, cards=cards, shuffle=shuffle,
                           starred_only=starred_only, flip_cards=flip_cards)

@app.route('/jampacks/<int:set_id>/add_card', methods=['GET', 'POST'])
def add_card(set_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    this_set_response = supabase.table('study_sets').select('*').eq('id', set_id).eq('user_id', user_id).execute()
    this_set = this_set_response.data[0] if this_set_response.data else None
    if not this_set:
        return jsonify({'error': 'Study set not found'}), 404
    if request.method == 'POST':
        if 'generate' in request.form:
            # Handle AI-generated cards
            text = f"Generate {request.form.get('num_cards', 10)} flashcards based on the following text:\n"
            text += request.form.get('text', '')
            try:
                flashcards = compose(text)
                for card in flashcards:
                    new_card = {
                        'question': card['question'],
                        'answer': card['answer'],
                        'study_set_id': set_id
                    }
                    supabase.table('flash_cards').insert(new_card).execute()
                flash(f"{len(flashcards)} cards added successfully!", "success")
            except Exception as e:
                flash(f"Error generating cards: {str(e)}", "error")
        else:
            # Handle manually added card
            question = request.form.get('question')
            answer = request.form.get('answer')
            if not question or not answer:
                return jsonify({'error': 'Both question and answer are required'}), 400
            new_card = {
                'question': question,
                'answer': answer,
                'study_set_id': set_id
            }
            supabase.table('flash_cards').insert(new_card).execute()
            flash("Card added successfully!", "success")
        return redirect(url_for('study_set', set_id=set_id))
    return render_template('add_card.html', study_set=this_set)

@app.route('/jampack_generator', methods=['GET', 'POST'])
def jampack_generator():
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    if request.method == 'POST':
        text = "Analyze the provided text and generate "
        text += request.form.get('num_cards', 10)  # Default to 10 if not provided
        text += " flashcards.\n"
        text += request.form.get('text')
        # Call OpenAI API to analyze text and generate flashcards
        try:
            flashcards = compose(text)
            title = request.form.get('title')
            new_set = {
                'title': title,
                'user_id': user_id
            }
            new_set_response = supabase.table('study_sets').insert(new_set).execute()
            new_set_id = new_set_response.data[0]['id']
            for card in flashcards:
                new_card = {
                    'question': card['question'],
                    'answer': card['answer'],
                    'study_set_id': new_set_id
                }
                supabase.table('flash_cards').insert(new_card).execute()
            flash(f"Jampack '{title}' created successfully with {len(flashcards)} cards!", "success")
            return redirect(url_for('dashboard'))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return render_template('jampack_generator.html')

def compose(text):
    response = openai.ChatCompletion.create(
        model="gpt-4-turbo",
        messages=[
            {
                "role": "system",
                "content":
                    """Generate the desire number of flashcards. Format each flashcard with the following structure.

                    (question to be displayed on the front of the flashcard):(answer to be displayed on the back of the flashcard) 

                    Not that if the desired number of flashcards is 10, for example, this does not mean 5 questions and 5 answers. 

                    It means 10 total flashcards (which implies 10 questions and 10 corresponding answers).

                    Use a colon to separate the question from the answer. Place each flashcard on a new line. Ensure that colons and new lines are used exclusively for separating questions from answers and one flashcard from another, respectively. Avoid using colons or new lines within questions or answers.

                    Below is an example of provided text, followed by an adequate example of a response generated by you. 

                    Provided text: George Washington, the first President of the United States, is often referred to as the Father of His Country for his pivotal role in the founding of the nation. Born on February 22, 1732, in Westmoreland County, Virginia, Washington emerged as a key leader during the American Revolutionary War, serving as the commander-in-chief of the Continental Army. His leadership and perseverance were instrumental in securing American independence from British rule. After the war, Washington presided over the Constitutional Convention of 1787, where the U.S. Constitution was drafted, and he was subsequently elected as the nation's first president, serving two terms from 1789 to 1797. Washington's presidency set many precedents, including the peaceful transfer of power, and his farewell address warned against political parties and foreign alliances. He passed away on December 14, 1799, at his Mount Vernon estate, leaving behind a legacy of integrity, leadership, and dedication to the principles of democracy and republicanism.

                    Adequate response:
                    Who is often referred to as the Father of His Country?:George Washington
                    What role did George Washington serve during the American Revolutionary War?:Commander-in-chief of the Continental Army
                    What year was George Washington born?:1732
                    In which county and state was George Washington born?:Westmoreland County, Virginia
                    What significant event did George Washington preside over in 1787?:The Constitutional Convention
                    What are two major themes of George Washington's farewell address?:Warning against political parties and foreign alliances
                    When and where did George Washington die?:December 14, 1799, at his Mount Vernon estate

                    Additionally, you may receive input text that is clearly already sorted in term-definition or question-answer format. If that is the case, please intuitively sort the text to match our format. Below is an example of this scenario. 

                    Provided text:
                    Hola=Hello
                    Adiós=Goodbye
                    Por favor=Please
                    Gracias=Thank you
                    Sí=Yes
                    No=No
                    Amigo=Friend
                    Familia=Family
                    Casa=House
                    Comida=Food
                    Agua=Water
                    Amor=Love
                    Libro=Book
                    Gato=Cat
                    Perro=Dog
                    Escuela=School
                    Día=Day
                    Noche=Night
                    Sol=Sun
                    Luna=Moon

                    Adequate response:
                    Hola:Hello
                    Adiós:Goodbye
                    Por favor:Please
                    Gracias:Thank you
                    Sí:Yes
                    No:No
                    Amigo:Friend
                    Familia:Family
                    Casa:House
                    Comida:Food
                    Agua:Water
                    Amor:Love
                    Libro:Book
                    Gato:Cat
                    Perro:Dog
                    Escuela:School
                    Día:Day
                    Noche:Night
                    Sol:Sun
                    Luna:Moon

                    Lastly, you may be provided text that resembles a more general request, such as “Make me a study set about current world leaders.” A study set may also be referred to as a 'Jampack'. A Jampack is synonymous with a study set. In this case, you must intuitively create a study set (using the usual colon and new line format) that has reasonable questions and reasonable answers. An example of this scenario is below.

                    Provided text: Create a study set for the colors of the rainbow.

                    Adequate response:
                    What is the first color of the rainbow?:Red
                    What is the second color of the rainbow?:Orange
                    What is the third color of the rainbow?:Yellow
                    What is the fourth color of the rainbow?:Green
                    What is the fifth color of the rainbow?:Blue
                    What is the sixth color of the rainbow?:Purple

                    And finally, you may be provided with text that includes a request to shorten a given study set, followed by the study set that is to be shortened. The range of knowledge covered by this shorter flashcard set should have the same scope as the original, however, make the cards more big-picture-focused as needed to reach the desired number of flashcards. Of course, you must use the usual colon and new line format in your response. Below is an example of this scenario, along with an adequate response. 

                    Provided text: Shorten this flashcard set to 5 flashcards while covering the same range of material.
                    Who is often referred to as the Father of His Country?:George Washington
                    What role did George Washington serve during the American Revolutionary War?:Commander-in-chief of the Continental Army
                    What year was George Washington born?:1732
                    In which county and state was George Washington born?:Westmoreland County, Virginia
                    What significant event did George Washington preside over in 1787?:The Constitutional Convention
                    What are two major themes of George Washington's farewell address?:Warning against political parties and foreign alliances
                    When and where did George Washington die?:December 14, 1799, at his Mount Vernon estate

                    Adequate response:
                    Who was the first US president, who served from 1789 to 1797?:Washington
                    What major battle did George Washington achieve victory in during the American Revolutionary War?:Battle of Yorktown
                    What significant precedents did George Washington establish during his presidency?:Cabinet system and peaceful transfer of power
                    When and where was George Washington born?:February 22, 1732, in Westmoreland County, Virginia
                    What is George Washington’s legacy celebrated for?:His role as a symbol of American ideals and governance"""
            },
            {
                "role": "user",
                "content": text
            }
        ]
    )
    # Check if the response contains choices and the message has content
    if not response.choices or not response.choices[0].message['content']:
        raise ValueError("No choices or content returned from API")
    # Process the API response to extract flashcard data
    flashcards_raw = response.choices[0].message['content'].strip().split('\n')
    formatted_flashcards = []
    for card in flashcards_raw:
        if ':' in card:
            question, answer = card.split(':', 1)
            formatted_flashcards.append({"question": question.strip(), "answer": answer.strip()})
    return formatted_flashcards

@app.route('/rapid_review/<int:set_id>', methods=['GET', 'POST'])
def rapid_review(set_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    this_set_response = supabase.table('study_sets').select('*').eq('id', set_id).eq('user_id', user_id).execute()
    this_set = this_set_response.data[0] if this_set_response.data else None
    if request.method == 'POST':
        text = "Analyst the following text and generate flashcards.\nShorten this flashcard set to "
        text += str(request.form.get('text'))
        text += " flashcards, while covering the same range of material. When possible, make sure to not simply group " \
                "combine the text of different flashcards, but rather, remodel the flashcards so that they touch " \
                "more so on big picture main ideas than hyper-specific, small details.\n"
        cards_response = supabase.table('flash_cards').select('*').eq('study_set_id', set_id).execute()
        cards = cards_response.data
        for card in cards:
            text += card.question
            text += ":"
            text += card.answer
            text += "\n"
        text += "\n"
        try:
            flashcards = compose(text)
            title = this_set['title']
            title += " (Rapid Review)"
            new_set = {
                'title': title,
                'user_id': user_id
            }
            new_set_response = supabase.table('study_sets').insert(new_set).execute()
            new_set_id = new_set_response.data[0]['id']
            for card in flashcards:
                new_card = {
                    'question': card['question'],
                    'answer': card['answer'],
                    'study_set_id': new_set_id
                }
                supabase.table('flash_cards').insert(new_card).execute()
            flash(f"Jampack '{title}' created successfully with {len(flashcards)} cards!", "success")
            return redirect(url_for('dashboard'))
        except Exception as e:
            return jsonify({"error": str(e)}), 500
    return render_template('rapid_review.html', study_set=this_set)

@app.route('/jampacks/<int:set_id>/edit_card/', defaults={'card_id': None})
@app.route('/jampacks/<int:set_id>/edit_card/<int:card_id>', methods=['GET', 'POST'])
def edit_card(set_id, card_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    this_set_response = supabase.table('study_sets').select('*').eq('id', set_id).eq('user_id', user_id).execute()
    this_set = this_set_response.data[0] if this_set_response.data else None
    if not this_set:
        return jsonify({'error': 'Study set not found'}), 404
    if card_id is None:
        # If no card_id is provided, edit the first card
        this_card_response = supabase.table('flash_cards').select('*').eq('study_set_id', set_id).limit(1).execute()
    else:
        this_card_response = supabase.table('flash_cards').select('*').eq('id', card_id).eq('study_set_id', set_id).execute()
    
    this_card = this_card_response.data[0] if this_card_response.data else None
    if not this_card:
        flash('No card to edit.', 'error')
        return redirect(url_for('study_set', set_id=set_id))
    if request.method == 'POST':
        this_card['question'] = request.form.get('question')
        this_card['answer'] = request.form.get('answer')
        supabase.table('flash_cards').update(this_card).eq('id', this_card['id']).execute()
        return redirect(url_for('study_set', set_id=set_id))
    return render_template('edit_card.html', study_set=this_set, card=this_card)

@app.route('/jampacks/<int:set_id>/delete_card/', defaults={'card_id': None})
@app.route('/jampacks/<int:set_id>/delete_card/<int:card_id>', methods=['GET'])
def delete_card(set_id, card_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    this_set_response = supabase.table('study_sets').select('*').eq('id', set_id).eq('user_id', user_id).execute()
    this_set = this_set_response.data[0] if this_set_response.data else None
    if not this_set:
        return jsonify({'error': 'Jampack not found'}), 404
    card_to_delete_response = supabase.table('flash_cards').select('*').eq('id', card_id).eq('study_set_id', set_id).execute()
    card_to_delete = card_to_delete_response.data[0] if card_to_delete_response.data else None
    if not card_to_delete:
        flash('No card to delete.', 'error')
        return redirect(url_for('study_set', set_id=set_id))
    else:
        supabase.table('flash_cards').delete().eq('id', card_id).execute()
    return redirect(url_for('study_set', set_id=set_id))

@app.route('/jampacks/<int:set_id>/star_card/<int:card_id>', methods=['POST'])
def star_card(set_id, card_id):
    user_id = session.get('user_id')
    if not user_id:
        return redirect(url_for('home'))
    card_response = supabase.table('flash_cards').select('*').eq('id', card_id).eq('study_set_id', set_id).execute()
    card = card_response.data[0] if card_response.data else None
    if not card:
        return jsonify({'error': 'Card not found'}), 404
    card['starred'] = not card.get('starred', False)
    supabase.table('flash_cards').update({'starred': card['starred']}).eq('id', card_id).execute()
    return jsonify({'success': True, 'starred': card.starred})

if __name__ == '__main__':
    app.run()
