# This file is part of PULP.
#
# PULP is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# PULP is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with PULP.  If not, see <http://www.gnu.org/licenses/>.

from django.db.models import Q
from django.shortcuts import render

from rest_framework import status
from rest_framework import generics
from rest_framework.response import Response
from rest_framework.views import APIView # class-based views
from rest_framework.decorators import api_view # for function-based views

from explore.models import Article, ArticleTFIDF, Experiment, ExperimentIteration, ArticleFeedback
from explore.serializers import ArticleSerializer
from explore.utils import *

from nltk.stem import SnowballStemmer
from sklearn.preprocessing import normalize
from scipy.sparse.linalg import spsolve

import collections
import sys
import random
import operator
import numpy
import json
import time

#from profilehooks import profile, coverage, timecall


DEFAULT_NUM_ARTICLES = 10

#class UserViewSet(viewsets.ModelViewSet):
#    queryset = User.objects.all()
#    serializer_class = UserSerializer

class GetArticle(generics.RetrieveAPIView) :
    queryset = Article.objects.all()
    serializer_class = ArticleSerializer

#class GetArticleOld(APIView) :
#    def get(self, request, article_id) :
#        try :
#            article = Article.objects.get(id=article_id)
#
#        except Article.DoesNotExist :
#            return Response(status=status.HTTP_404_NOT_FOUND)
#
#        serializer = ArticleSerializer(article)
#        return Response(serializer.data)


@api_view(['GET'])
def logout_view(request):
    #logout(request)
    return Response(status=status.HTTP_200_OK)

def get_top_articles_tfidf_old(query_terms, n) :
    """
    return top n articles using tfidf terms,
    ranking articles using okapi_bm25
    """

    try :
        tfidf_query = reduce(operator.or_, [ Q(term=t) for t in query_terms ])
        tfidfs = ArticleTFIDF.objects.select_related('article').filter(tfidf_query)
        #articles = get_top_articles(tfidfs, num_articles)
        #print "%d articles found (%s)" % (len(articles), ','.join([str(a.id) for a in articles]))
    
    except ArticleTFIDF.DoesNotExist :
        print "no articles found containing search terms"
        return []

    tmp = {}

    for tfidf in tfidfs :
        if tfidf.article not in tmp :
            tmp[tfidf.article] = 1.0

        tmp[tfidf.article] *= tfidf.value

    ranking = sorted(tmp.items(), key=lambda x : x[1], reverse=True)

    return [ r[0] for r in ranking[:n] ]

# query terms - a list of stemmed query words
# n - the number of articles to return
#@timecall(immediate=True)
def get_top_articles_tfidf(query_terms, n) :
    tfidf = load_sparse_tfidf()
    features = load_features_tfidf()
    #articles = Article.objects.all()

    tmp = {}

    for qt in query_terms :
        if qt not in features :
            continue

        findex = features[qt]

        #print numpy.nonzero(tfidf[:, findex])

        for aindex in numpy.nonzero(tfidf[:, findex])[0] :
            akey = aindex.item()
            if akey not in tmp :
                tmp[akey] = 1.0

            tmp[akey] *= tfidf[aindex,findex]

    ranking = sorted(tmp.items(), key=lambda x : x[1], reverse=True)

    # XXX
#    stemmer = SnowballStemmer('english')
#    for i,r in enumerate(ranking[:n]) :
#        with open("tfidf_testing.%d" % i, 'w') as f :
#            a = articles[r[0]]
#            for word,stem in [ (word,stemmer.stem(word)) for word in a.title.split() + a.abstract.split() ] :
#                if stem not in features :
#                    continue
#                
#                print >> f, stem, word, tfidf[r[0], features[stem]]
    # XXX

    #return [ articles[r[0]] for r in ranking[:n] ]
    id2article = dict([ (a.id, a) for a in Article.objects.filter(pk__in=[ r[0]+1 for r in ranking[:n] ]) ])
    top_articles = [ id2article[i[0]+1] for i in ranking[:n] ]
    
    return top_articles

print "loading sparse linrel"
X = load_sparse_linrel()

def linrel(articles, feedback, data, start, n, mew=1.0, exploration_rate=0.1) :
    assert len(articles) == len(feedback), "articles and feedback are not the same length"

    X = data

    num_articles = X.shape[0]
    num_features = X.shape[1]

    X_t = X[ numpy.array(articles) ]
    X_tt = X_t.transpose()

    I = mew * scipy.sparse.identity(num_features, format='dia')

    W = spsolve((X_tt * X_t) + I, X_tt)
    A = X * W

    Y_t = numpy.matrix(feedback).transpose()

    tmpA = numpy.array(A.todense())
    normL2 = numpy.matrix(numpy.sqrt(numpy.sum(tmpA * tmpA, axis=1))).transpose()

    # W * Y_t is the keyword weights
    K = W * Y_t

    mean = A * Y_t
    variance = (exploration_rate / 2.0) * normL2
    I_t = mean + variance


    linrel_ordered = numpy.argsort(I_t.transpose()[0]).tolist()[0]
    top_n = []

    for i in linrel_ordered[::-1] :
        if i not in articles :
            top_n.append(i)

        if len(top_n) == (start + n) :
            break

    top_n = top_n[-n:]

    return top_n, \
           mean[ numpy.array(top_n) ].transpose().tolist()[0], \
           variance[ numpy.array(top_n) ].transpose().tolist()[0], \
           K

def get_keyword_stats(articles, keyword_weights) :

    K = keyword_weights
    top_articles = articles

    # XXX this is temporary, for experimenting only
    #     and needs to be stored in the database
    stemmer = SnowballStemmer('english')

    used_keywords = collections.defaultdict(list)

    for i in top_articles :
        for word,stem in [ (word,stemmer.stem(word)) for word in i.title.split() + i.abstract.split() ] :
            used_keywords[stem].append(word)

    keyword_stats = {}
    features = load_features_linrel()

    for word in used_keywords :
        if word not in features :
            continue

        index = features[word]
        value = K[int(index),0]**2

        for key in used_keywords[word] :
            keyword_stats[key] = value

    keyword_sum = sum(keyword_stats.values())
    
    for i in keyword_stats :
        keyword_stats[i] /= keyword_sum

    return keyword_stats

def get_article_stats(articles, exploitation, exploration) :
    article_stats = {}

    for index,article_id in enumerate(articles) :
        article_stats[article_id] = (exploitation[index], exploration[index])

    return article_stats

#@timecall(immediate=True)
#@profile
def get_top_articles_linrel(e, start, count, exploration) :
    global X
    
    articles_obj = ArticleFeedback.objects.filter(experiment=e).exclude(selected=None)
    articles_npid = [ a.article.id - 1 for a in articles_obj ] # database is 1-indexed, numpy is 0-indexed
    feedback = [ 1.0 if a.selected else 0.0 for a in articles_obj ]
    data = X

    articles_new_npid,mean,variance,kw_weights = linrel(articles_npid, 
                                                        feedback, 
                                                        data, 
                                                        start,
                                                        count,
                                                        exploration_rate=exploration)

    articles_new_dbid = [ i + 1 for i in articles_new_npid ] # database is 1-indexed, numpy is 0-indexed
    articles_new_obj = Article.objects.filter(pk__in=articles_new_dbid)

    # everything comes out of the database sorted by id...
    tmp = dict([ (a.id, a) for a in articles_new_obj ])

    return [ tmp[id] for id in articles_new_dbid ], \
           get_keyword_stats(articles_new_obj, kw_weights), \
           get_article_stats(articles_new_dbid, mean, variance)

def get_running_experiments(user) :
    return Experiment.objects.filter(user=user, state=Experiment.RUNNING)

#def create_experiment(sid, user, num_documents) :
#    get_running_experiments(sid).update(state=Experiment.ERROR)
#
#    e = Experiment()
#
#    e.sessionid = sid
#    e.number_of_documents = num_documents
#    #e.user = user
#
#    e.save()
#
#    return e

def get_experiment(user) :
    e = get_running_experiments(user)

    if len(e) != 1 :
        e.update(state=Experiment.ERROR)
        return None

    return e[0]

def create_iteration(experiment, articles) :
    ei = ExperimentIteration()
    ei.experiment = experiment
    ei.iteration = experiment.number_of_iterations
    ei.save()

    for article in articles :
        afb = ArticleFeedback()
        afb.article = article
        afb.experiment = experiment
        afb.iteration = ei
        afb.save()

    return ei

def get_last_iteration(e) :
    return ExperimentIteration.objects.get(experiment=e, iteration=e.number_of_iterations-1)

def add_feedback(ei, articles) :
    feedback = ArticleFeedback.objects.filter(iteration=ei)

    for fb in feedback :
        print "saving clicked=%s for %s" % (str(fb.article.id in articles), str(fb.article.id))
        fb.selected = fb.article.id in articles
        fb.save()

def get_unseen_articles(e) :
    return Article.objects.exclude(pk__in=[ a.article.id for a in ArticleFeedback.objects.filter(experiment=e) ])

@api_view(['GET'])
def textual_query(request) :
    if request.method == 'GET' :
        # experiments are started implicitly with a text query
        # and experiments are tagged with the session id
#        request.session.flush()
        #print request.session.session_key

        # get parameters from url
        # q : query string
        if 'q' not in request.GET or 'participant_id' not in request.GET :
            return Response(status=status.HTTP_400_BAD_REQUEST)
        
        query_string = request.GET['q']
        
        stemmer = SnowballStemmer('english')
        query_terms = [ stemmer.stem(term) for term in query_string.lower().split() ]

        print "query: %s" % str(query_terms)

        if not len(query_terms) :
            return Response(status=status.HTTP_400_BAD_REQUEST)

        
        # participant_id : user id
        participant_id = request.GET['participant_id']
        try :
            user = User.objects.get(username=participant_id)

        except User.DoesNotExist :
            return Response(status=status.HTTP_400_BAD_REQUEST)


        # article-count : number of articles to return
        num_articles = int(request.GET.get('article-count', DEFAULT_NUM_ARTICLES))

        print "article-count: %d" % (num_articles)

        # create new experiment
        e = get_experiment(user)
        e.number_of_documents = num_articles

        # get documents with TFIDF-based ranking 
        articles = get_top_articles_tfidf(query_terms, num_articles)

        # add random articles if we don't have enough
        fill_count = num_articles - len(articles)
        if fill_count :
            print "only %d articles found, adding %d random ones" % (len(articles), fill_count)
            articles += random.sample(Article.objects.all(), fill_count)
        
        # create new experiment iteration
        # save new documents to current experiment iteration 
        create_iteration(e, articles)
        e.number_of_iterations += 1
        e.save()

        serializer = ArticleSerializer(articles, many=True)
        return Response(serializer.data)

@api_view(['GET'])
def selection_query(request) :
    start_time = time.time()
    if request.method == 'GET' :
        # get experiment object
        if 'participant_id' not in request.GET :
            return Response(status=status.HTTP_400_BAD_REQUEST)

        participant_id = request.GET['participant_id']
        try :
            user = User.objects.get(username=participant_id)

        except User.DoesNotExist :
            return Response(status=status.HTTP_400_BAD_REQUEST)
        
        e = get_experiment(user)
        # get previous experiment iteration
        try :
            ei = get_last_iteration(e)

        except ExperimentIteration.DoesNotExist :
            return Response(status=status.HTTP_400_BAD_REQUEST)

        # get parameters from url
        # ?id=x&id=y&id=z
        try :
            selected_documents = [ int(i) for i in request.GET.getlist('id') ]

        except ValueError :
            return Response(status=status.HTTP_400_BAD_REQUEST)
        
        print selected_documents

        # only sent this in iteration 1, do the last iteration is 0
        if ei.iteration == 0 :
            try :
                apply_exploration = bool(request.GET['exploratory'])
        
            except :
                return Response(status=status.HTTP_400_BAD_REQUEST)

            if apply_exploration :
                e.exploration_rate = e.base_exploration_rate

        # add selected documents to previous experiment iteration
        add_feedback(ei, selected_documents)

        # get documents with ML algorithm 
        # remember to exclude all the articles that the user has already been shown
        rand_articles, keywords, article_stats = get_top_articles_linrel(e, 
                                                                         0, 
                                                                         e.number_of_documents, 
                                                                         e.exploration_rate)

        print "%d articles (%s)" % (len(rand_articles), ','.join([str(a.id) for a in rand_articles]))

        # create new experiment iteration
        # save new documents to current experiment iteration
        create_iteration(e, rand_articles)
        e.number_of_iterations += 1
        e.save()

        # response to client
        serializer = ArticleSerializer(rand_articles, many=True)
        article_data = serializer.data
        for i in article_data :
            mean,var = article_stats[i['id']]
            i['mean'] = mean
            i['variance'] = var

        print time.time() - start_time
        return Response({'articles' : article_data, 'keywords' : keywords})

@api_view(['GET'])
def system_state(request) :
    return Response(status=status.HTTP_404_NOT_FOUND)    

    if request.method == 'GET' :
        e = get_experiment(request.session.session_key)
        try :
            start = int(request.GET['start'])
            count = int(request.GET['count'])
        
        except KeyError :
            return Response(status=status.HTTP_404_NOT_FOUND)
        except ValueError :
            return Response(status=status.HTTP_404_NOT_FOUND)

        print "start = %d, count = %d" % (start, count)

        articles, keyword_stats, article_stats = get_top_articles_linrel(e, start, count, 0.1)
        serializer = ArticleSerializer(articles, many=True)    

        return Response({'article_data' : article_stats, 'keywords' : keyword_stats, 'all_articles' : serializer.data})

@api_view(['GET'])
def end_search(request) :
    if request.method == 'GET' :
        if 'participant_id' not in request.GET :
            return Response(status=status.HTTP_400_BAD_REQUEST)

        participant_id = request.GET['participant_id']
        
        try :
            user = User.objects.get(username=participant_id)

        except User.DoesNotExist :
            return Response(status=status.HTTP_400_BAD_REQUEST)

        e = get_experiment(user)
        e.state = Experiment.COMPLETE
        e.save()
        return Response(status=status.HTTP_200_OK)

@api_view(['GET'])
def index(request) :
    return render(request, 'index.html')

@api_view(['GET'])
def visualization(request) :
    return render(request, 'visualization.html')

@api_view(['GET'])
def setup_experiment(request) :
    # /setup?participant_id=1234&task_type=0&exploration_rate=1&task_order=1

    try :
        participant_id      = request.GET['participant_id']
        task_type           = int(request.GET['task_type'])
        exploration_rate    = float(request.GET['exploration_rate'])

    except :
        return Response(status=status.HTTP_400_BAD_REQUEST)

    if task_type not in (0, 1) :
        return Response(status=status.HTTP_400_BAD_REQUEST)

    if exploration_rate < 0.0 :
        return Response(status=status.HTTP_400_BAD_REQUEST)

    try :
        user = User.objects.get(username=participant_id)
    
    except User.DoesNotExist :
        user = User()
        user.username = participant_id
        user.save()

    # check if there are any running experiments 
    # and set them to ERROR
    Experiment.objects.filter(user=user, state=Experiment.RUNNING).update(state=Experiment.ERROR)
    
    # create experiment
    e = Experiment()
    e.user                  = user
    e.task_type             = Experiment.EXPLORATORY_TYPE if task_type == 0 else Experiment.LOOKUP_TYPE
    e.num_of_documents      = DEFAULT_NUM_ARTICLES
    e.base_exploration_rate = exploration_rate
    e.save()

    return Response(status=status.HTTP_200_OK)

