"""Recommendation engine.

Design: the candidate pool is built from *input-specific* sources first -
TMDB's per-title "recommendations" lists (collaborative signal), the
filmographies of people behind the user's picks, and the similar-lists of
titles they've liked - with genre discovery demoted to popularity-sorted
filler. Scoring weights those same input-specific signals above generic
quality, so different inputs produce different results. A same-country/
language boost ranks homegrown content first, replacing the old
international-diversity bonuses.

The module is dependency-injected: callers pass a `ctx` dict carrying the
HTTP fetch helper and API configuration, so this module never imports the
Flask app.
"""

import math
import random
from concurrent.futures import ThreadPoolExecutor

MOVIE_GENRES = {
    28: 'Action', 12: 'Adventure', 16: 'Animation', 35: 'Comedy', 80: 'Crime',
    99: 'Documentary', 18: 'Drama', 10751: 'Family', 14: 'Fantasy',
    36: 'History', 27: 'Horror', 10402: 'Music', 9648: 'Mystery',
    10749: 'Romance', 878: 'Science Fiction', 10770: 'TV Movie',
    53: 'Thriller', 10752: 'War', 37: 'Western'
}

TV_GENRES = {
    10759: 'Action & Adventure', 16: 'Animation', 35: 'Comedy', 80: 'Crime',
    99: 'Documentary', 18: 'Drama', 10751: 'Family', 10762: 'Kids',
    9648: 'Mystery', 10763: 'News', 10764: 'Reality',
    10765: 'Sci-Fi & Fantasy', 10766: 'Soap', 10767: 'Talk',
    10768: 'War & Politics', 37: 'Western'
}

# TV crew roles that indicate real authorship of a series; tv_credits rarely
# uses a literal "Creator" job, so showrunner-ish roles stand in.
TV_AUTHORSHIP_JOBS = {'Creator', 'Executive Producer', 'Writer', 'Director', 'Producer'}

LANGUAGE_NAMES = {
    'id': 'Indonesian', 'ko': 'Korean', 'ja': 'Japanese', 'fr': 'French',
    'es': 'Spanish', 'de': 'German', 'hi': 'Hindi', 'zh': 'Chinese',
    'cn': 'Chinese', 'it': 'Italian', 'pt': 'Portuguese', 'th': 'Thai',
    'tr': 'Turkish', 'ta': 'Tamil', 'te': 'Telugu', 'ru': 'Russian',
    'da': 'Danish', 'sv': 'Swedish', 'no': 'Norwegian', 'pl': 'Polish',
    'tl': 'Filipino', 'ms': 'Malay', 'vi': 'Vietnamese'
}

COUNTRY_NAMES = {
    'US': 'American', 'GB': 'British', 'KR': 'Korean', 'JP': 'Japanese',
    'ID': 'Indonesian', 'IN': 'Indian', 'FR': 'French', 'DE': 'German',
    'ES': 'Spanish', 'IT': 'Italian', 'BR': 'Brazilian', 'MX': 'Mexican',
    'TH': 'Thai', 'TR': 'Turkish', 'CN': 'Chinese', 'TW': 'Taiwanese',
    'HK': 'Hong Kong', 'CA': 'Canadian', 'AU': 'Australian'
}

# How many of the user's picks must share a language/country before we treat
# it as their "home" preference. With the 3-4 picks the UI collects, 3 means
# a clear deliberate pattern rather than a coincidence.
HOME_THRESHOLD = 3


def _dominant(values, threshold=HOME_THRESHOLD):
    """The value appearing at least `threshold` times, or None."""
    counts = {}
    for value in values:
        if value:
            counts[value] = counts.get(value, 0) + 1
    best = max(counts.items(), key=lambda kv: kv[1], default=(None, 0))
    return best[0] if best[1] >= threshold else None


def _run_jobs(jobs):
    """Run [(kind, source_id, url, params, cache_key, fetch)] in parallel.

    Returns [(kind, source_id, data)] for jobs that produced data.
    """
    results = []
    if not jobs:
        return results
    with ThreadPoolExecutor(max_workers=len(jobs)) as executor:
        futures = {
            executor.submit(fetch, url, params, cache_key): (kind, source_id)
            for kind, source_id, url, params, cache_key, fetch in jobs
        }
        for future in futures:
            kind, source_id = futures[future]
            data = future.result()
            if data:
                results.append((kind, source_id, data))
    return results


def _feedback_adjustment(item_genres, profile):
    """Genre-level score delta from likes/dislikes.

    Dislikes weigh more per occurrence than likes: telling us what you don't
    want is a stronger, rarer signal than a like, and a repeatedly-rejected
    genre should decisively sink a candidate rather than just nudge it.
    """
    delta = 0
    for genre in item_genres:
        delta += 12 * min(profile['liked_genres'].get(genre, 0), 3)
        delta -= 18 * min(profile['disliked_genres'].get(genre, 0), 3)
    return delta


def _quality_score(vote_average, vote_count):
    """Rating weighted by how many people stand behind it, as a tiebreaker
    rather than a dominant signal. ~13 for an acclaimed blockbuster, ~6 for a
    well-liked small film, near 0 for barely-rated entries."""
    return min(vote_average * math.log10(vote_count + 1) * 0.4, 15)


def _weighted_pick(scored, pool_size=8):
    """Pick from the top of the ranking, weighted sharply toward the best so
    variety never means settling for a weak match."""
    scored.sort(key=lambda x: x[1], reverse=True)
    pool = scored[:pool_size]
    weights = [max(score, 1) ** 2 for _, score in pool]
    return random.choices(pool, weights=weights)[0]


def _genre_alignment(candidate_genres, input_genre_counts):
    """Supporting signal: overlap between the candidate's genres and the
    inputs' genre distribution, capped so it can't dominate."""
    score = sum(4 * min(input_genre_counts.get(g, 0), 3) for g in candidate_genres)
    return min(score, 30)


# ---------------------------------------------------------------------------
# Movies
# ---------------------------------------------------------------------------

def recommend_movie(picks, profile, excluded_ids, ctx):
    fetch = ctx['fetch']
    base = ctx['tmdb_base']
    key = ctx['tmdb_key']

    input_genre_counts = {}
    pick_titles = {}
    for pick in picks:
        pick_titles[pick.get('id')] = pick.get('title', '')
        for genre in pick.get('genre_ids', []):
            input_genre_counts[genre] = input_genre_counts.get(genre, 0) + 1

    home_lang = _dominant([p.get('original_language') for p in picks])

    # Phase A: who directed the picks (needed before filmography fetches).
    credit_results = _run_jobs([
        ('credits', pick['id'], f"{base}/movie/{pick['id']}/credits",
         {'api_key': key}, ('movie_credits', pick['id']), fetch)
        for pick in picks if pick.get('id')
    ])
    director_counts, director_names = {}, {}
    for _, _, data in credit_results:
        for crew in data.get('crew', []):
            if crew.get('job') == 'Director' and crew.get('id'):
                director_counts[crew['id']] = director_counts.get(crew['id'], 0) + 1
                director_names[crew['id']] = crew.get('name', '')
    top_directors = sorted(director_counts.items(), key=lambda kv: kv[1], reverse=True)[:2]

    # Phase B: gather candidates, most input-specific sources first.
    jobs = []
    for pick in picks:
        if pick.get('id'):
            jobs.append(('similar', pick['id'], f"{base}/movie/{pick['id']}/recommendations",
                         {'api_key': key}, ('movie_recs', pick['id']), fetch))
    for liked_id in profile['liked_ids'][:4]:
        jobs.append(('liked_similar', liked_id, f"{base}/movie/{liked_id}/recommendations",
                     {'api_key': key}, ('movie_recs', str(liked_id)), fetch))
    for director_id, _ in top_directors:
        jobs.append(('person', director_id, f"{base}/person/{director_id}/movie_credits",
                     {'api_key': key}, ('director_films', director_id), fetch))
    genre_filter = '|'.join(str(g) for g, _ in
                            sorted(input_genre_counts.items(), key=lambda kv: kv[1], reverse=True)[:3])
    for page in (1, 2):
        jobs.append(('filler', None, f"{base}/discover/movie", {
            'api_key': key, 'with_genres': genre_filter,
            'sort_by': 'popularity.desc', 'vote_count.gte': 300, 'page': page
        }, ('discover_movie_pop', genre_filter, page), fetch))
    if home_lang:
        jobs.append(('filler', None, f"{base}/discover/movie", {
            'api_key': key, 'with_genres': genre_filter,
            'with_original_language': home_lang,
            'sort_by': 'popularity.desc', 'vote_count.gte': 100, 'page': 1
        }, ('discover_movie_home', genre_filter, home_lang), fetch))

    candidates = {}   # id -> {'item', 'similar_sources': set, 'person': id|None}

    def note(item, kind, source_id):
        cid = item.get('id')
        if not cid or cid in excluded_ids:
            return
        entry = candidates.setdefault(cid, {'item': item, 'similar_sources': set(), 'person': None})
        if kind in ('similar', 'liked_similar'):
            entry['similar_sources'].add(source_id)
        elif kind == 'person':
            entry['person'] = source_id

    for kind, source_id, data in _run_jobs(jobs):
        if kind == 'person':
            # Person credits list every role unfiltered; keep only films the
            # person actually directed so affinity claims stay truthful.
            for item in data.get('crew', []):
                if item.get('job') == 'Director' and item.get('vote_count', 0) >= 100:
                    note(item, kind, source_id)
        else:
            for item in data.get('results', []):
                note(item, kind, source_id)

    # Phase C: filter and score.
    scored = []
    for cid, entry in candidates.items():
        item = entry['item']
        if (item.get('vote_average', 0) < 6.0 or item.get('vote_count', 0) < 30
                or not item.get('overview') or not item.get('release_date')):
            continue

        genres = item.get('genre_ids', [])
        score = 25 * min(len(entry['similar_sources']), 4)
        if entry['person']:
            score += 30 * min(director_counts.get(entry['person'], 0), 4)
        if home_lang and item.get('original_language') == home_lang:
            score += 25
        score += _genre_alignment(genres, input_genre_counts)
        score += _feedback_adjustment(genres, profile)
        score += _quality_score(item.get('vote_average', 0), item.get('vote_count', 0))
        scored.append((entry, score))

    if not scored:
        return None

    winner, _ = _weighted_pick(scored)
    item = dict(winner['item'])
    item['genres'] = [{'id': g, 'name': MOVIE_GENRES.get(g, f'Genre {g}')}
                      for g in item.get('genre_ids', [])]

    # Reasoning: lead with the most specific true fact we have.
    parts = []
    person = winner['person']
    if person and director_counts.get(person, 0) > 1:
        parts.append(f"Another film from {director_names[person]}, who directed {director_counts[person]} of your picks.")
    elif person:
        parts.append(f"Directed by {director_names[person]}, whose work you already picked.")
    else:
        contributing = [pick_titles[s] for s in winner['similar_sources'] if s in pick_titles][:2]
        if contributing:
            parts.append(f"A favorite among people who loved {' and '.join(contributing)}.")
        elif winner['similar_sources']:
            parts.append("Picked up from titles you recently loved.")
        else:
            shared = [MOVIE_GENRES[g] for g in item.get('genre_ids', []) if g in input_genre_counts and g in MOVIE_GENRES]
            if shared:
                parts.append(f"A strong match for your {', '.join(shared[:2]).lower()} taste.")
            else:
                parts.append("A widely loved pick that fits your taste profile.")
    if home_lang and home_lang != 'en' and item.get('original_language') == home_lang:
        lang_name = LANGUAGE_NAMES.get(home_lang)
        if lang_name:
            parts.append(f"A homegrown {lang_name} film, like your picks.")
    if len(parts) < 3 and item.get('vote_average', 0) >= 7.5:
        parts.append(f"Rated {item['vote_average']:.1f}/10 by {item.get('vote_count', 0):,} viewers.")
    item['reasoning'] = ' '.join(parts[:3])
    return item


# ---------------------------------------------------------------------------
# TV
# ---------------------------------------------------------------------------

def recommend_tv(picks, profile, excluded_ids, ctx):
    fetch = ctx['fetch']
    base = ctx['tmdb_base']
    key = ctx['tmdb_key']

    input_genre_counts = {}
    pick_titles = {}
    input_countries = []
    for pick in picks:
        pick_titles[pick.get('id')] = pick.get('name', '')
        for genre in pick.get('genre_ids', []):
            input_genre_counts[genre] = input_genre_counts.get(genre, 0) + 1
        countries = pick.get('origin_country') or []
        input_countries.append(countries[0] if countries else None)

    home_country = _dominant(input_countries)
    reality_ok = 10764 in input_genre_counts

    # Phase A: who created the picks.
    detail_results = _run_jobs([
        ('details', pick['id'], f"{base}/tv/{pick['id']}",
         {'api_key': key}, ('tv_details', pick['id']), fetch)
        for pick in picks if pick.get('id')
    ])
    creator_counts, creator_names = {}, {}
    for _, _, data in detail_results:
        for creator in data.get('created_by', []):
            if creator.get('id'):
                creator_counts[creator['id']] = creator_counts.get(creator['id'], 0) + 1
                creator_names[creator['id']] = creator.get('name', '')
    top_creators = sorted(creator_counts.items(), key=lambda kv: kv[1], reverse=True)[:2]

    # Phase B: gather candidates.
    jobs = []
    for pick in picks:
        if pick.get('id'):
            jobs.append(('similar', pick['id'], f"{base}/tv/{pick['id']}/recommendations",
                         {'api_key': key}, ('tv_recs', pick['id']), fetch))
    for liked_id in profile['liked_ids'][:4]:
        jobs.append(('liked_similar', liked_id, f"{base}/tv/{liked_id}/recommendations",
                     {'api_key': key}, ('tv_recs', str(liked_id)), fetch))
    for creator_id, _ in top_creators:
        # Person credits rather than discover's with_people, which does not
        # actually constrain TV results.
        jobs.append(('person', creator_id, f"{base}/person/{creator_id}/tv_credits",
                     {'api_key': key}, ('tv_person_credits', creator_id), fetch))
    genre_filter = '|'.join(str(g) for g, _ in
                            sorted(input_genre_counts.items(), key=lambda kv: kv[1], reverse=True)[:3])
    for page in (1, 2):
        jobs.append(('filler', None, f"{base}/discover/tv", {
            'api_key': key, 'with_genres': genre_filter,
            'sort_by': 'popularity.desc', 'vote_count.gte': 150, 'page': page
        }, ('discover_tv_pop', genre_filter, page), fetch))
    if home_country:
        jobs.append(('filler', None, f"{base}/discover/tv", {
            'api_key': key, 'with_genres': genre_filter,
            'with_origin_country': home_country,
            'sort_by': 'popularity.desc', 'vote_count.gte': 50, 'page': 1
        }, ('discover_tv_home', genre_filter, home_country), fetch))

    candidates = {}

    def note(item, kind, source_id):
        cid = item.get('id')
        if not cid or cid in excluded_ids:
            return
        entry = candidates.setdefault(cid, {'item': item, 'similar_sources': set(), 'person': None})
        if kind in ('similar', 'liked_similar'):
            entry['similar_sources'].add(source_id)
        elif kind == 'person':
            entry['person'] = source_id

    for kind, source_id, data in _run_jobs(jobs):
        if kind == 'person':
            for item in data.get('crew', []):
                if item.get('job') in TV_AUTHORSHIP_JOBS and item.get('vote_count', 0) >= 50:
                    note(item, kind, source_id)
        else:
            for item in data.get('results', []):
                note(item, kind, source_id)

    # Phase C: filter and score.
    scored = []
    for cid, entry in candidates.items():
        item = entry['item']
        if (item.get('vote_average', 0) < 6.0 or item.get('vote_count', 0) < 30
                or not item.get('overview')):
            continue
        genres = item.get('genre_ids', [])
        if not reality_ok and 10764 in genres:
            continue

        score = 25 * min(len(entry['similar_sources']), 4)
        if entry['person']:
            score += 30 * min(creator_counts.get(entry['person'], 0), 4)
        if home_country and home_country in (item.get('origin_country') or []):
            score += 25
        score += _genre_alignment(genres, input_genre_counts)
        score += _feedback_adjustment(genres, profile)
        score += _quality_score(item.get('vote_average', 0), item.get('vote_count', 0))
        scored.append((entry, score))

    if not scored:
        return None

    winner, _ = _weighted_pick(scored)
    item = dict(winner['item'])
    item['genres'] = [{'id': g, 'name': TV_GENRES.get(g, f'Genre {g}')}
                      for g in item.get('genre_ids', [])]

    parts = []
    person = winner['person']
    if person and creator_counts.get(person, 0) > 1:
        parts.append(f"From {creator_names[person]}, the creator behind {creator_counts[person]} of your picks.")
    elif person:
        parts.append(f"From {creator_names[person]}, whose work you already picked.")
    else:
        contributing = [pick_titles[s] for s in winner['similar_sources'] if s in pick_titles][:2]
        if contributing:
            parts.append(f"A favorite among people who loved {' and '.join(contributing)}.")
        elif winner['similar_sources']:
            parts.append("Picked up from shows you recently loved.")
        else:
            shared = [TV_GENRES[g] for g in item.get('genre_ids', []) if g in input_genre_counts and g in TV_GENRES]
            if shared:
                parts.append(f"A strong match for your {', '.join(shared[:2]).lower()} taste.")
            else:
                parts.append("A widely loved series that fits your taste profile.")
    if home_country and home_country != 'US' and home_country in (item.get('origin_country') or []):
        country_name = COUNTRY_NAMES.get(home_country)
        if country_name:
            parts.append(f"A homegrown {country_name} series, like your picks.")
    if len(parts) < 3 and item.get('vote_average', 0) >= 7.5:
        parts.append(f"Rated {item['vote_average']:.1f}/10 by {item.get('vote_count', 0):,} viewers.")
    item['reasoning'] = ' '.join(parts[:3])
    return item


# ---------------------------------------------------------------------------
# Books
# ---------------------------------------------------------------------------

def recommend_book(picks, profile, excluded_ids, ctx):
    fetch_books = ctx['fetch_books']

    category_counts = {}
    author_counts = {}
    for pick in picks:
        for category in pick.get('categories', []):
            category_counts[category] = category_counts.get(category, 0) + 1
        for author in pick.get('authors', []):
            author_counts[author] = author_counts.get(author, 0) + 1

    home_lang = _dominant([p.get('language') for p in picks])

    top_categories = sorted(category_counts.items(), key=lambda kv: kv[1], reverse=True)[:3]
    top_authors = sorted(author_counts.items(), key=lambda kv: kv[1], reverse=True)[:2]

    # Google Books has no "similar titles" endpoint, so authors are the most
    # input-specific source, categories the thematic one. When the picks share
    # a language, a language-restricted category search keeps results homegrown.
    searches = []
    for author, _ in top_authors:
        searches.append((f'inauthor:"{author}"', 15, None))
    for category, _ in top_categories:
        searches.append((f'subject:{category}', 20, None))
        if home_lang and home_lang != 'en':
            searches.append((f'subject:{category}', 20, home_lang))

    candidates = {}
    with ThreadPoolExecutor(max_workers=max(len(searches), 1)) as executor:
        futures = [executor.submit(fetch_books, query, excluded_ids, max_results, lang)
                   for query, max_results, lang in searches]
        for future in futures:
            for book in future.result() or []:
                candidates.setdefault(book['id'], book)

    scored = []
    for book in candidates.values():
        if not book.get('overview'):
            continue
        categories = book.get('categories', [])
        authors = book.get('authors', [])

        author_affinity = max((author_counts.get(a, 0) for a in authors), default=0)
        score = 30 * min(author_affinity, 4)
        if home_lang and book.get('language') == home_lang:
            score += 25
        score += _genre_alignment(categories, category_counts)
        score += _feedback_adjustment(categories, profile)
        score += min(book.get('vote_average', 0) * 3, 15)
        scored.append((book, score))

    if not scored:
        return None

    book, _ = _weighted_pick(scored)
    book = dict(book)

    parts = []
    shared_authors = [a for a in book.get('authors', []) if a in author_counts]
    if shared_authors:
        author = shared_authors[0]
        picked = author_counts[author]
        if picked > 1:
            parts.append(f"Another book from {author}, who wrote {picked} of your picks.")
        else:
            parts.append(f"Another book from {author}, whose work you already picked.")
    else:
        shared = [c for c in book.get('categories', []) if c in category_counts]
        if shared:
            parts.append(f"A strong match for your {', '.join(shared[:2]).lower()} shelves.")
        else:
            parts.append("Thematically connected to your picks.")
    if home_lang and home_lang != 'en' and book.get('language') == home_lang:
        lang_name = LANGUAGE_NAMES.get(home_lang)
        if lang_name:
            parts.append(f"Written in {lang_name}, like your picks.")
    if len(parts) < 3 and book.get('vote_average', 0) >= 4.0:
        parts.append("Highly rated by readers.")
    book['reasoning'] = ' '.join(parts[:3])
    return book
