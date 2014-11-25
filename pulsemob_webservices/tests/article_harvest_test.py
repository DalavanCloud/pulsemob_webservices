import ConfigParser
import json
import unittest
import os
from urlparse import parse_qs
from httmock import urlmatch, HTTMock
import psycopg2
import solr
import solr_util
from harvest import harvest


class HarvestJobTests(unittest.TestCase):

    def test_harvest(self):

        @urlmatch(netloc=r'(.*\.)?articlemeta\.scielo\.org$', path=r'^/api/v1/article/identifiers$')
        def article_identifiers_mock(url, request):
            path = os.path.dirname(os.path.realpath(__file__))
            query = parse_qs(url.query)
            if query["offset"][0] == "0":
                result = open('{0}/fixtures/{1}'.format(path, self.input_file)).read()
            else:
                result = open('{0}/fixtures/empty_article_identifiers.json'.format(path)).read()

            return result


        @urlmatch(netloc=r'(.*\.)?articlemeta\.scielo\.org$', path=r'^/api/v1/article$')
        def article_mock(url, request):
            query = parse_qs(url.query)
            dict = {}
            dict["code"] = query["code"]
            result = str(dict)
            result = result.replace("'", "\"")

            return result

        def delete_article_entry(id):
            self.operations.append("D,{0}".format(id))

        def add_update_article_entry(id, document, action):
            self.operations.append("{0},{1}".format(action, id))

        def test_using_input(config, input_file, expected_output_file):
            self.input_file = input_file
            self.operations = []

            harvest(config.get("harvest", "article_meta_uri"),
            "article",
            data_source_name,
            "article_test_data",
            config.get("harvest", "pg_shared_folder_output"),
            config.get("harvest", "pg_shared_folder_input"),
            (add_update_article_entry, delete_article_entry)
            )

            path = os.path.dirname(os.path.realpath(__file__))
            with open('{0}/fixtures/{1}'.format(path, expected_output_file)) as file:
                right_operations = [line.rstrip() for line in file]

            sorted_operations = sorted(self.operations)
            self.assertEqual(right_operations,
                             sorted_operations,
                             "The returned list does not match the content of file '{0}'.\n"
                             "Returned: {1}\n"
                             "Expected: {2}".format(expected_output_file, str(sorted_operations), str(right_operations))
            )



        path = os.path.dirname(os.path.realpath(__file__))
        config = ConfigParser.ConfigParser()
        config.read('{0}/harvest_test.cfg'.format(path))

        print "Testing harvest..."
        data_source_name = config.get("harvest", "data_source_name")
        with psycopg2.connect(data_source_name) as conn:
            with conn.cursor() as curs:
                curs.execute("TRUNCATE article_test_data")

        with HTTMock(article_identifiers_mock, article_mock):
            test_using_input(config, "article_identifiers_0.json", "article_output_0.txt")
            test_using_input(config, "article_identifiers_1.json", "article_output_1.txt")
            test_using_input(config, "article_identifiers_2.json", "article_output_2.txt")

        print "Testing Solr adding entries..."
        path = os.path.dirname(os.path.realpath(__file__))
        code = "X0718-34372014000100009"
        doc_ret = json.loads(open('{0}/fixtures/article_{1}.json'.format(path, code)).read())
        args = solr_util.get_solr_args_from_article(doc_ret)
        solr_uri = config.get("harvest", "solr_uri")
        solr_conn = solr.SolrConnection(solr_uri)
        solr_conn.add(commit=True, **args)
        solr_conn.commit(True, True, True)

        response = solr_conn.query(id=code)
        for hit in response.results:
            print hit

        # print "Testing Solr delete entries..."
        # solr_conn.delete(id="S0718-3437201400010000X")


def suite():
    suite = unittest.TestSuite()
    suite.addTest(unittest.makeSuite(HarvestJobTests, 'test'))
    return suite