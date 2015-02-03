from django.conf.urls import url, include
from django.http import HttpResponseRedirect, HttpResponse
from rest_framework import routers, serializers, viewsets
from models import Feed, Publication, User, UserFavorite, UserFeedExclusion, UserPublicationFeedExclusion, FONT_SIZE_OPTIONS, LANGUAGE_OPTIONS
from pprint import pprint
from multiprocessing import Process
import json
import Queue
import threading
import sys
import services
import ast
from settings import *

# no debug for us
DEBUG = True


def get_user_by_header_request(request):
    facebook_id = request.META.get('HTTP_FACEBOOKID', None)
    google_id = request.META.get('HTTP_GOOGLEID', None)

    if facebook_id is not None:
        try:
            print('Getting by ', facebook_id)
            user = User.objects.get(facebook_id=facebook_id)
            return user
        except User.DoesNotExist:
            pass
        except:
            print "Unexpected error:", sys.exc_info()[0]
            raise
    else:
        try:
            user = User.objects.get(google_id=google_id)
            return user
        except User.DoesNotExist:
            pass
        except:
            print "Unexpected error:", sys.exc_info()[0]
            raise


# Login function.
def login(self):
    try:
        if self.method == 'POST':
            data = json.loads(self.body)
            email = data.get('email', None)
            name = data.get('name', None)
            language = data.get('language', None)
            font_size = data.get('font_size', None)

            facebook_id = self.META.get('HTTP_FACEBOOKID', None)
            google_id = self.META.get('HTTP_GOOGLEID', None)

            # Try get by email. If the result is empty or has length > 1, user = None for now.
            if email is not None:
                try:
                    user = User.objects.get(email=email)
                except User.DoesNotExist:
                    user = None
                # Unnecessary because I never update email field.
                # except User.MultipleObjectsReturned:
                #     if facebook_id is not None:
                #         user = User.objects.get(email=email, facebook_id=facebook_id)
                #     elif google_id is not None:
                #         user = User.objects.get(email=email, google_id=google_id)

            # If email or user is None, try to get by social id.
            if email is None or user is None:
                if facebook_id is not None:
                    try:
                        user = User.objects.get(facebook_id=facebook_id)
                    except User.DoesNotExist:
                        user = None
                elif google_id is not None:
                    try:
                        user = User.objects.get(google_id=google_id)
                    except User.DoesNotExist:
                        user = None

            if user is None:
                user = User(None, None, None, email, name, facebook_id, google_id, language, font_size)
                user.save()
            else:
                if user.facebook_id is None and facebook_id is not None:
                    user.facebook_id = facebook_id
                    user.save()
                elif user.google_id is None and google_id is not None:
                    user.google_id = google_id
                    user.save()

            response = dict()
            response['user'] = user.to_dict()
            response['solr_version'] = services.solr_repository_version()
            response['feed_exclusions'] = list(UserFeedExclusion.objects.values_list('feed_id', flat=True)
                                               .filter(user=user))
            response['favorites'] = list(UserFavorite.objects.values_list('article_id', flat=True).filter(user=user))

            publications_feeds_exclusions = list(UserPublicationFeedExclusion.objects.filter(user_id=user.id))
            print (publications_feeds_exclusions)
            list_publications_feeds_exclusions = {}
            for publications_feeds_exclusion in publications_feeds_exclusions:
                if publications_feeds_exclusion.feed.id not in list_publications_feeds_exclusions:
                    list_publications_feeds_exclusions[publications_feeds_exclusion.feed.id] = []
                list_publications_feeds_exclusions[publications_feeds_exclusion.feed.id].\
                    append(publications_feeds_exclusion.publication.id)

            response['publication_feed_exclusions'] = list_publications_feeds_exclusions

            return HttpResponse(json.dumps(response), status=200, content_type="application/json")
        else:
            return HttpResponse('', status=405)
    except:
        print "Unexpected error:", sys.exc_info()[0]


def home(self):
    if self.method == 'GET':
        user = get_user_by_header_request(self)
        user_id = user.id

        feeds = list(Feed.objects.all())
        feed_exclusions = list(UserFeedExclusion.objects.filter(user_id=user_id).values_list('feed_id', flat=True))

        publication_feed_exclusions_aux = UserPublicationFeedExclusion.objects.filter(user_id=user_id)
        publication_feed_exclusions_dict = {}

        for pfea in publication_feed_exclusions_aux:
            if pfea.feed.id not in publication_feed_exclusions_dict:
                publication_feed_exclusions_dict[pfea.feed.id] = []

            publication_feed_exclusions_dict[pfea.feed.id].append(pfea.publication.id)

        q = Queue.Queue()

        count_calls = 0
        for feed in feeds:
            if feed.id not in feed_exclusions:
                count_calls += 1
                if feed.id in publication_feed_exclusions_dict:
                    t = threading.Thread(target=services.article_find_by_feed_id_and_not_publication_id,
                                         args=(feed.id, publication_feed_exclusions_dict[feed.id], q))
                else:
                    t = threading.Thread(target=services.article_find_by_feed_id, args=(feed.id, q))

                t.daemon = True
                t.start()

        response = []

        i = 0
        while i < count_calls:
            s = q.get()
            response.append(s)
            i += 1

        return HttpResponse(json.dumps(response), status=200, content_type="application/json")
    else:
        return HttpResponse('', status=405)


def read_favorite(self):
    if self.method == 'GET':
        user = get_user_by_header_request(self)
        user_id = user.id

        response = services.article_find_favorite_by_user_id(user_id)
        return HttpResponse(json.dumps(response), status=200)
    else:
        return HttpResponse('', status=405)


def create_favorite(self):
    if self.method == 'POST':
        try:
            user = get_user_by_header_request(self)
            user_id = user.id
            data = json.loads(self.body)
            article_id = data.get('article_id', None)

            if article_id is None:
                return HttpResponse('You should provide article_id parameter.', status=400)

            try:
                UserFavorite.objects.get(user_id=user_id, article_id=article_id)
            except UserFavorite.DoesNotExist:
                user_favorite = UserFavorite(None, user_id, article_id)
                user_favorite.save()

            return HttpResponse(json.dumps({}), status=200)
        except:
            print "Unexpected error:", sys.exc_info()[0]
    else:
        return HttpResponse('', status=405)


def delete_favorite(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        user_id = user.id
        data = json.loads(self.body)
        article_id = data.get('article_id', None)

        try:
            user_favorite = UserFavorite.objects.get(user_id=user_id, article_id=article_id)
            user_favorite.delete()
        except UserFavorite.DoesNotExist:
            pass

        return HttpResponse(json.dumps({}), status=200)
    else:
        return HttpResponse('', status=405)


def read_favorite(self):
    if self.method == 'GET':
        try:
            user = get_user_by_header_request(self)
            user_id = user.id

            if user_id is None:
                return HttpResponse('', status=400)

            article_ids = []
            user_favorites = UserFavorite.objects.filter(user_id=user_id)
            for user_favorite in user_favorites:
                article_ids.append(user_favorite.article_id)

            return HttpResponse(json.dumps(article_ids), status=200)
        except:
            print "Unexpected error:", sys.exc_info()[0]
    else:
        return HttpResponse('', status=405)


def create_feed_exclusion(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        user_id = user.id
        data = json.loads(self.body)
        feed_id = data.get('feed_id', None)

        if feed_id is None:
            return HttpResponse('You should provide feed_id parameter.', status=400)

        try:
            UserFeedExclusion.objects.get(user_id=user_id, feed_id=feed_id)
        except UserFeedExclusion.DoesNotExist:
            user_feed_exclusion = UserFeedExclusion(None, user_id, feed_id)
            user_feed_exclusion.save()

        return HttpResponse(json.dumps({}), status=200)
    else:
        return HttpResponse('', status=405)


def delete_feed_exclusion(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        user_id = user.id
        data = json.loads(self.body)
        feed_id = data.get('feed_id', None)

        if feed_id is None:
            return HttpResponse('You should provide feed_id parameter.', status=400)

        try:
            user_feed_exclusion = UserFeedExclusion.objects.get(user_id=user_id, feed_id=feed_id)
            user_feed_exclusion.delete()
        except UserFeedExclusion.DoesNotExist:
            pass

        return HttpResponse(json.dumps({}), status=200)
    else:
        return HttpResponse('', status=405)


def create_feed_publication_exclusion(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        user_id = user.id
        data = json.loads(self.body)
        feed_id = data.get('feed_id', None)
        publication_id = data.get('publication_id', None)

        if feed_id is None or publication_id is None:
            return HttpResponse('You should provide feed_id and publication_id parameters.', status=400)

        try:
            UserPublicationFeedExclusion.objects.get(user_id=user_id, feed_id=feed_id, publication_id=publication_id)
        except UserPublicationFeedExclusion.DoesNotExist:
            user_feed__publication_exclusion = UserPublicationFeedExclusion(None, user_id, publication_id, feed_id)
            user_feed__publication_exclusion.save()

        return HttpResponse(json.dumps({}), status=200)
    else:
        return HttpResponse('', status=405)


def delete_feed_publication_exclusion(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        user_id = user.id
        data = json.loads(self.body)
        feed_id = data.get('feed_id', None)
        publication_id = data.get('publication_id', None)

        if feed_id is None or publication_id is None:
            return HttpResponse('You should provide feed_id and publication_id parameters.', status=400)

        try:
            user_feed__publication_exclusion = UserPublicationFeedExclusion.objects.get(user_id=user_id, feed_id=feed_id, publication_id=publication_id)
            user_feed__publication_exclusion.delete()
        except UserPublicationFeedExclusion.DoesNotExist:
            pass

        return HttpResponse(json.dumps({}), status=200)
    else:
        return HttpResponse('', status=405)


def read_user(self):
    if self.method == 'GET':
        user = get_user_by_header_request(self)
        user_id = user.id

        response = services.user_get_general_state(user_id)

        return HttpResponse(json.dumps(response), status=200)
    else:
        return HttpResponse('', status=405)


def user_change_language(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        data = json.loads(self.body)
        language = data.get('language', None)

        if language is None:
            return HttpResponse('You should provide language parameter: PT, EN or ES.', status=400)

        if not language == 'PT' and not language == 'EN' and not language == 'ES':
            return HttpResponse('Malformed syntax in language parameter.', status=400)

        user.language = language
        user.save()

        return HttpResponse(json.dumps({}), status=200)

    else:
        return HttpResponse('', status=405)


def user_change_font_size(self):
    if self.method == 'POST':
        user = get_user_by_header_request(self)
        data = json.loads(self.body)
        font_size = data.get('font_size', None)

        if font_size is None:
            return HttpResponse('You should provide font_size parameter: S, M or L.', status=400)

        if not font_size == 'S' and not font_size == 'M' and not font_size == 'L':
            return HttpResponse('Malformed syntax in font_size parameter.', status=400)

        user.font_size = font_size
        user.save()
        return HttpResponse(json.dumps({}), status=200)

    else:
        return HttpResponse('', status=405)


def list_feed_publications(self):
    if self.method == 'GET':
        try:
            response = dict()

            response['solr_version'] = services.solr_repository_version()

            feeds = list(Feed.objects.all())
            response['feeds'] = {}

            for feed in feeds:
                response['feeds'][feed.id] = feed.to_dict()
                publications = list(Publication.objects.values_list('id', flat=True).filter(feeds=feed))
                response['feeds'][feed.id]['publications'] = publications

            publications = list(Publication.objects.all())
            response['publications'] = {}
            for publication in publications:
                response['publications'][publication.id] = publication.to_dict()

            return HttpResponse(json.dumps(response), status=200)
        except:
            print "Unexpected error:", sys.exc_info()[0]
            raise
    else:
        return HttpResponse('', status=405)


def solr_version(self):
    if self.method == 'GET':
        try:
            return HttpResponse(json.dumps(services.solr_repository_version()), status=200)
        except:
            print "Unexpected error:", sys.exc_info()[0]
            raise
    else:
        return HttpResponse('', status=405)

# Wire up our API using automatic URL routing.
# Additionally, we include login URLs for the browsable API.
urlpatterns = [
    url(r'^login', login),
    url(r'^home', home),

    url(r'^solr/version', solr_version),

    url(r'^favorite/create', create_favorite),
    url(r'^favorite/read', read_favorite),
    url(r'^favorite/delete', delete_favorite),

    url(r'^feed/publications/list', list_feed_publications),

    url(r'^preferences/feed/exclusion/create', create_feed_exclusion),
    url(r'^preferences/feed/exclusion/delete', delete_feed_exclusion),

    url(r'^preferences/feed/publication/exclusion/create', create_feed_publication_exclusion),
    url(r'^preferences/feed/publication/exclusion/delete', delete_feed_publication_exclusion),

    url(r'^user/language', user_change_language),
    url(r'^user/font', user_change_font_size),
]