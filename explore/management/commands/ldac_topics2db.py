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

import xml.sax 
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from explore.models import Topic
from sys import stderr

class Command(BaseCommand) :
    args = '<beta file> <vocab file>'
    help = 'loads topics from txt file into DB'

    def handle(self, *args, **options) :
        """Function to handle and process data from a file containing topics and their corresponding keywords, and store them in a database.
        Parameters:
            - args (list): A list of arguments, where the first argument is the file containing topics and the second argument is the file containing the vocabulary index.
            - options (dict): A dictionary of options, if applicable.
        Returns:
            - None: This function does not return any value, but instead stores the topics and their keywords in a database.
        Processing Logic:
            - Read the vocabulary index from the specified file.
            - For each line in the file containing topics and keywords, extract the top 5 keywords and store them in a new file.
            - Create a new Topic object and save it in the database.
            - For each keyword in the list of keywords, create a new TopicKeyword object and save it in the database.
            - Print the number of topics added to the database."""
        

        NUM_KEYWORDS = 5

        with open(args[1]) as f :
            vocab_index = dict(enumerate(f.readline(5_000_000).strip().split()))

        print >> stderr, "read %d words in vocabulary" % len(vocab_index)

        # arxiv_cs_example/topic_top_keywords
        with open(args[0]) as f :
            linenum = 0

            g = open('topic_keywords.txt', 'w')

            for line in f :
                linenum += 1

                line = line.strip()
                if not line :
                    continue

                keywords = ','.join([ vocab_index[i[0]] for i in sorted(enumerate([ float(v) for v in line.split() ]), reverse=True, key=lambda x : x[1])[:NUM_KEYWORDS] ])

                print >> g, ' '.join([ vocab_index[i[0]] for i in sorted(enumerate([ float(v) for v in line.split() ]), reverse=True, key=lambda x : x[1])[:10] ])

                #try :
                #    name,keywords = line.split()
                #
                #except ValueError :
                #    print >> stderr, "Error: too many tokens, line %d" % linenum
                #    continue
                #
                #keywords = keywords.split(',')

                with transaction.atomic() :
                    t = Topic()
                    t.label = keywords
                    t.save()

                    #for k in keywords :
                    #    kw = TopicKeyword()
                    #    kw.topic = t
                    #    kw.keyword = k
                    #    kw.save()

                #print >> stderr, "saved topic %s" % name

        g.close()
        print >> stderr, "added %d topics" % (Topic.objects.count())

