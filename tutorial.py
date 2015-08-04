from flask import Blueprint, render_template, current_app, abort, g, \
    request, url_for, session, flash, redirect
from galatea.tryton import tryton
from galatea.utils import get_tryton_language
from flask.ext.paginate import Pagination
from flask.ext.babel import gettext as _, lazy_gettext
from flask.ext.mail import Mail, Message
from trytond.config import config as tryton_config
from whoosh import index
from whoosh.qparser import MultifieldParser
import os

tutorial = Blueprint('tutorial', __name__, template_folder='templates')

DISPLAY_MSG = lazy_gettext('Displaying <b>{start} - {end}</b> of <b>{total}</b>')

Website = tryton.pool.get('galatea.website')
Tutorial = tryton.pool.get('galatea.tutorial')
Comment = tryton.pool.get('galatea.tutorial.comment')
User = tryton.pool.get('galatea.user')

GALATEA_WEBSITE = current_app.config.get('TRYTON_GALATEA_SITE')
LIMIT = current_app.config.get('TRYTON_PAGINATION_TUTORIAL_LIMIT', 20)
COMMENTS = current_app.config.get('TRYTON_TUTORIAL_COMMENTS', True)
WHOOSH_MAX_LIMIT = current_app.config.get('WHOOSH_MAX_LIMIT', 500)
TUTORIAL_SCHEMA_PARSE_FIELDS = ['title', 'content']

def _visibility():
    visibility = ['public']
    if session.get('logged_in'):
        visibility.append('register')
    if session.get('manager'):
        visibility.append('manager')
    return visibility

@tutorial.route("/search/", methods=["GET"], endpoint="search")
@tryton.transaction()
def search(lang):
    '''Search'''
    websites = Website.search([
        ('id', '=', GALATEA_WEBSITE),
        ], limit=1)
    if not websites:
        abort(404)
    website, = websites

    WHOOSH_TUTORIAL_DIR = current_app.config.get('WHOOSH_TUTORIAL_DIR')
    if not WHOOSH_TUTORIAL_DIR:
        abort(404)

    db_name = current_app.config.get('TRYTON_DATABASE')
    locale = get_tryton_language(lang)

    schema_dir = os.path.join(tryton_config.get('database', 'path'),
        db_name, 'whoosh', WHOOSH_TUTORIAL_DIR, locale.lower())

    if not os.path.exists(schema_dir):
        abort(404)

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('.tutorials', lang=g.language),
        'name': _('Tutorial'),
        }, {
        'slug': url_for('.search', lang=g.language),
        'name': _('Search'),
        }]

    q = request.args.get('q')
    if not q:
        return render_template('tutorial-search.html',
                tutorials=[],
                breadcrumbs=breadcrumbs,
                pagination=None,
                q=None,
                )

    # Get tutorials from schema results
    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    # limit
    if request.args.get('limit'):
        try:
            limit = int(request.args.get('limit'))
            session['tutorial_limit'] = limit
        except:
            limit = LIMIT
    else:
        limit = session.get('tutorial_limit', LIMIT)

    # Search
    ix = index.open_dir(schema_dir)
    query = q.replace('+', ' AND ').replace('-', ' NOT ')
    query = MultifieldParser(TUTORIAL_SCHEMA_PARSE_FIELDS, ix.schema).parse(query)

    with ix.searcher() as s:
        all_results = s.search_page(query, 1, pagelen=WHOOSH_MAX_LIMIT)
        total = all_results.scored_length()
        results = s.search_page(query, page, pagelen=LIMIT) # by pagination
        res = [result.get('id') for result in results]

    domain = [
        ('id', 'in', res),
        ('active', '=', True),
        ('visibility', 'in', _visibility()),
        ]
    order = [('tutorial_create_date', 'DESC'), ('id', 'DESC')]

    tutorials = Tutorial.search(domain, order=order)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    return render_template('tutorial-search.html',
            website=website,
            tutorials=tutorials,
            pagination=pagination,
            breadcrumbs=breadcrumbs,
            q=q,
            )

@tutorial.route("/comment", methods=['POST'], endpoint="comment")
@tryton.transaction()
def comment(lang):
    '''Add Comment'''
    websites = Website.search([
        ('id', '=', GALATEA_WEBSITE),
        ], limit=1)
    if not websites:
        abort(404)
    website, = websites

    tutorial = request.form.get('tutorial')
    comment = request.form.get('comment')

    domain = [
        ('id', '=', tutorial),
        ('active', '=', True),
        ('visibility', 'in', _visibility()),
        ('websites', 'in', [GALATEA_WEBSITE]),
        ]
    tutorials = Tutorial.search(domain, limit=1)
    if not tutorials:
        abort(404)
    tutorial, = tutorials

    if not website.tutorial_comment:
        flash(_('Not available to publish comments.'), 'danger')
    elif not website.tutorial_anonymous and not session.get('user'):
        flash(_('Not available to publish comments and anonymous users.' \
            ' Please, login in'), 'danger')
    elif not comment or not tutorial:
        flash(_('Add a comment to publish.'), 'danger')
    else:
        c = Comment()
        c.tutorial = tutorial['id']
        c.user = session['user'] if session.get('user') \
            else website.tutorial_anonymous_user.id
        c.description = comment
        c.save()
        flash(_('Comment published successfully.'), 'success')

        mail = Mail(current_app)

        mail_to = current_app.config.get('DEFAULT_MAIL_SENDER')
        subject =  '%s - %s' % (current_app.config.get('TITLE'), _('New comment published'))
        msg = Message(subject,
                body = render_template('emails/tutorial-comment-text.jinja', tutorial=tutorial, comment=comment),
                html = render_template('emails/tutorial-comment-html.jinja', tutorial=tutorial, comment=comment),
                sender = mail_to,
                recipients = [mail_to])
        mail.send(msg)

    return redirect(url_for('.tutorial', lang=g.language, slug=tutorial['slug']))

@tutorial.route("/<slug>", endpoint="tutorial")
@tryton.transaction()
def tutorial_detail(lang, slug):
    '''Tutorial detail'''
    websites = Website.search([
        ('id', '=', GALATEA_WEBSITE),
        ], limit=1)
    if not websites:
        abort(404)
    website, = websites

    tutorials = Tutorial.search([
        ('slug', '=', slug),
        ('active', '=', True),
        ('visibility', 'in', _visibility()),
        ('websites', 'in', [GALATEA_WEBSITE]),
        ], limit=1)

    if not tutorials:
        abort(404)
    tutorial, = tutorials

    breadcrumbs = [{
        'slug': url_for('.tutorials', lang=g.language),
        'name': _('Tutorial'),
        }, {
        'slug': url_for('.tutorial', lang=g.language, slug=tutorial.slug),
        'name': tutorial.name,
        }]

    return render_template('tutorial-tutorial.html',
            website=website,
            tutorial=tutorial,
            breadcrumbs=breadcrumbs,
            )

@tutorial.route("/key/<key>", endpoint="key")
@tryton.transaction()
def key(lang, key):
    '''Tutorials by Key'''
    websites = Website.search([
        ('id', '=', GALATEA_WEBSITE),
        ], limit=1)
    if not websites:
        abort(404)
    website, = websites

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    # limit
    if request.args.get('limit'):
        try:
            limit = int(request.args.get('limit'))
            session['tutorial_limit'] = limit
        except:
            limit = LIMIT
    else:
        limit = session.get('tutorial_limit', LIMIT)

    domain = [
        ('metakeywords', 'ilike', '%'+key+'%'),
        ('active', '=', True),
        ('visibility', 'in', _visibility()),
        ('websites', 'in', [GALATEA_WEBSITE]),
        ]
    total = Tutorial.search_count(domain)
    offset = (page-1)*limit

    order = [('tutorial_create_date', 'DESC'), ('id', 'DESC')]
    tutorials = Tutorial.search(domain, offset, limit, order)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('.tutorials', lang=g.language),
        'name': _('Tutorial'),
        }, {
        'slug': url_for('.key', lang=g.language, key=key),
        'name': key,
        }]

    return render_template('tutorial-key.html',
            website=website,
            tutorials=tutorials,
            pagination=pagination,
            breadcrumbs=breadcrumbs,
            key=key,
            )

@tutorial.route("/user/<user>", endpoint="user")
@tryton.transaction()
def users(lang, user):
    '''Tutorials by User'''
    websites = Website.search([
        ('id', '=', GALATEA_WEBSITE),
        ], limit=1)
    if not websites:
        abort(404)
    website, = websites

    try:
        user = int(user)
    except:
        abort(404)

    users = User.search([
        ('id', '=', user)
        ], limit=1)
    if not users:
        abort(404)
    user, = users

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    # limit
    if request.args.get('limit'):
        try:
            limit = int(request.args.get('limit'))
            session['tutorial_limit'] = limit
        except:
            limit = LIMIT
    else:
        limit = session.get('tutorial_limit', LIMIT)

    domain = [
        ('user', '=', user.id),
        ('active', '=', True),
        ('visibility', 'in', _visibility()),
        ('websites', 'in', [GALATEA_WEBSITE]),
        ]
    total = Tutorial.search_count(domain)
    offset = (page-1)*limit

    if not total:
        abort(404)

    order = [('tutorial_create_date', 'DESC'), ('id', 'DESC')]
    tutorials = Tutorial.search(domain, offset, limit, order)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('.tutorials', lang=g.language),
        'name': _('Tutorial'),
        }, {
        'slug': url_for('.user', lang=g.language, user=user.id),
        'name': user.rec_name,
        }]

    return render_template('tutorial-user.html',
            website=website,
            tutorials=tutorials,
            user=user,
            pagination=pagination,
            breadcrumbs=breadcrumbs,
            )

@tutorial.route("/", endpoint="tutorials")
@tryton.transaction()
def tutorials(lang):
    '''Tutorials'''
    websites = Website.search([
        ('id', '=', GALATEA_WEBSITE),
        ], limit=1)
    if not websites:
        abort(404)
    website, = websites

    try:
        page = int(request.args.get('page', 1))
    except ValueError:
        page = 1

    # limit
    if request.args.get('limit'):
        try:
            limit = int(request.args.get('limit'))
            session['tutorial_limit'] = limit
        except:
            limit = LIMIT
    else:
        limit = session.get('tutorial_limit', LIMIT)

    domain = [
        ('active', '=', True),
        ('visibility', 'in', _visibility()),
        ('websites', 'in', [GALATEA_WEBSITE]),
        ]
    total = Tutorial.search_count(domain)
    offset = (page-1)*limit

    order = [('tutorial_create_date', 'DESC'), ('id', 'DESC')]
    tutorials = Tutorial.search(domain, offset, limit, order)

    pagination = Pagination(page=page, total=total, per_page=limit, display_msg=DISPLAY_MSG, bs_version='3')

    #breadcumbs
    breadcrumbs = [{
        'slug': url_for('.tutorials', lang=g.language),
        'name': _('Tutorial'),
        }]

    return render_template('tutorials.html',
            website=website,
            tutorials=tutorials,
            pagination=pagination,
            breadcrumbs=breadcrumbs,
            )
