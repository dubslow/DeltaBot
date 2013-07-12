# encoding: utf-8
from __future__ import division
import time
import logging
import re
import praw
import pprint
import urllib2

# 30 seconds for now, change to 60*60 for 1 hour
##### Shouldn't this be 30 minutes? If 60*60 is 1 hr, and 60*30 is half that,
##### How is 60*30 == 30 seconds?
PERIOD_SCAN = 60*30

# these can optionally be changed

TOKENS = [u'∆', u'&amp;#8710;', u'Δ']

# unnecessary now that we have wiki solution
#TRACKER_URL = "http://www.reddit.com/r/snorrrlax/comments/1adxhd/deltabots_delta_tracker/"

# ignore everything else
###########################

TOKEN_GROUP = u'(' + u'|'.join(TOKENS) + u')'
TOKEN_REGEX = u'(?<!["\'])%s(?!["\'])' % TOKEN_GROUP

# set up logging
logging.getLogger('requests').setLevel(logging.WARNING) # hide messages from requests

#strings for table updating
TABLE_HEAD = '\n\n| Rank | Username | Deltas |\n| :------: | ------ | ------: |'
TABLE_LEADER_ENTRY = "\n| 1 | **/u/%s** | [%s](// \"deltas received\") |"
TABLE_ENTRY = '\n| %s | /u/%s | [%s](// "deltas received") |'

class DeltaBot(object):
    def __init__(self, config, testmode=False):
        self.config = config

        logging.info('connecting to reddit')
        self.reddit = praw.Reddit(self.config.subreddit + ' bot', site_name=config.site_name)

        self.reddit.login(*[self.config.account['username'], self.config.account['password']])

        self.subreddit = self.reddit.get_subreddit(self.config.subreddit)

        self.testmode = testmode

    def award_delta(self, parent, comment):
        """ Awards a delta. """
        if self.testmode is True:
            print comment.parent_id

        elif self.add_points(parent.author):
            self.update_delta_tracker(comment)
            comment.reply(self.config.messages['confirmation'][0] % parent.author).distinguish()
            comment.author.send_message(self.config.private_message.format( \
            wiki_page_url = "http://www.reddit.com/r/%s/wiki/%s" % (self.config.subreddit, comment.author))
            logging.debug('Confirmation comment posted and message sent.')
        else:
            logging.warning('non-numeric flair for user %s, skipping adding points' % comment.author.name)

    def add_points(self, redditor, num_points=1):
        """ Recalculate a user's delta and update flair. """

        old_flair = self.subreddit.get_flair(redditor.name)
        if 'flair_css_class' not in old_flair or not old_flair['flair_css_class']:
            old_flair['flair_css_class'] = ''
        if not old_flair['flair_text']:
            old_flair['flair_text'] = ''
            old_points = 0
        else:
            try:
                old_points = int(old_flair['flair_text'].replace(u'∆', u''))
            except ValueError:
                logging.warning("Old flair wasn't numeric.")
                return False

        new_flair_str = str(old_points + num_points) + u'∆'
        if 'points' not in old_flair['flair_css_class']:
            new_flair_class = 'points ' + old_flair['flair_css_class']
        else:
            new_flair_class = old_flair['flair_css_class']
        self.subreddit.set_flair(redditor.name, new_flair_str, new_flair_class)
        return True

    #TODO: Seems slow. Can we streamline this?
    def find_delta(self, comment, check_confirmed=True):
        """ Search a comment to see whether or not there's a delta token. """
        if comment.is_root or not comment.submission.author:
            logging.debug('Comment or submission invalid.')
            return False
        logging.debug("Stripping blockquotes.")
        comment.body = self.strip_quotations(comment.body)

        logging.debug("Searching for token.")
        if re.search(TOKEN_REGEX, comment.body):
            # see if bot already confirmed
            replyers = [c.author.name.lower() for c in comment.replies if c.author]
            if self.reddit.get_info(thing_id=comment.parent_id).author == comment.author:
                logging.debug('commentor responded to self with delta')
                return False
            if check_confirmed:
                if self.config.account['username'].lower() in replyers:
                    logging.debug('already confirmed')
                    return False

            logging.debug("Getting parent.")
            parent = self.reddit.get_info(thing_id=comment.parent_id)
            if parent.author is None:
                logging.debug('parent.author is None')
                return False
            else:
                return parent
        logging.debug('delta token not found')
        return False

    def strip_quotations(self, comment_body):
        """ Delete quotations from reddit posts (by > token). """
        # TODO: this will strip ANY paragraph with ANY > symbol in it,
        # not just >s that indicate block quotes. Needs refinement.
        split_comment = comment_body.split("\n")
        stripped_comment = ""
        for paragraph in split_comment:
            if paragraph.find("&gt;") == -1:
                stripped_comment = stripped_comment+ paragraph
        return stripped_comment
    #TODO: This function is way, way too big and can be modularized. Do that.

    def scan(self, comments = None, before_id=None, limit = 500, newest_comment = None):
        """ Scan a given list of comments for delta tokens. If no list arg,
        then get newest comments from subreddit. If delta found, award delta.
        At end write newest comment id to file.
        """
        if comments == None:
            comments = [c for c in self.subreddit.get_comments(params={'before': before_id}, limit=limit)]
        logging.debug('scanning comments newer than %s' % str(before_id))
        for comment in comments:
            if type(comment) is praw.objects.MoreComments:
                # This shouldn't trigger since every comment is retrieved individually.
                # As opposed to en mass from a submission
                logging.debug("scanning a MoreComments object")
                self.scan(comments = comment.comments())

            if comment == None or comment.name == None or comment.author == None:
                logging.debug("Author or comment has been deleted.\n")
                continue
            else:
                logging.debug('scanning comment %s by %s' % \
                    (comment.name, comment.author.name))
                newest_comment = comment

            # see if there's a delta reply
            parent = self.find_delta(comment)
            if not parent:
                continue
            logging.info('new delta comment %s by %s to %s found' % \
                (comment.name, comment.author.name, parent.author.name))
            if parent.author.name.lower() == self.config.account['username'].lower():
                logging.debug('reply to bot detected, awarding no points')
                continue
            if self.is_parents_thread(comment):
                comment.reply(self.config.messages['broken_rule'][0]).distinguish()
                logging.debug("Submission's author can't get delta in \
                                own thread.")
                continue
            if self.multiple_deltas_thread(comment):
                comment.reply(self.config.messages['already_awarded'][0] % parent.author).distinguish()
                logging.debug("Disallowing comment: same user, multiple deltas, \
                                same thread")
                continue
            if len(comment.body) < 10:
                comment.reply(self.config.messages['too_little_text'][0] % parent.author).distinguish()
                logging.debug("Comment has too little text.")
                continue

            logging.debug("Awarding points.")
            self.award_delta(parent, comment)

        if newest_comment is None:
            logging.info('no new comments')
            return before_id

        logging.debug("Writing newest comment id to cache file.")
        self.write_previous_comment_id(newest_comment.name)
        return newest_comment.name

    # Incorporate this function back into scan() function?
    def is_parents_thread(self, comment):
        """ Does the thread belong to the comment's parent's author? """
        return self.reddit.get_info(thing_id=comment.parent_id).author == comment.submission.author

    def update_top_ten_list(self):
        """ Update the top 10 list with highest delta earners. """
        top_deltas = self.get_top_ten_deltas()
        logging.debug("Updating top 10 list.")
        delta_table = ["\n\n**Top Ten Viewchangers**", TABLE_HEAD,
                       TABLE_LEADER_ENTRY % ((top_deltas[0][u'user'], \
                        top_deltas[0][u'flair_text']))]

        for i in range(9):
            delta_table.append(TABLE_ENTRY % ((i+2, top_deltas[i+1][u'user'], \
                top_deltas[i+1][u'flair_text'])))

        settings = self.subreddit.get_settings()
        old_desc = settings[u'description']
        # IMPORTANT: this splits the description on the _____ token.
        # Don't use said token for anything other than dividing sections
        # or else this breaks.
        split_desc = old_desc.split("_____")
        split_desc[len(split_desc)-1] = "".join(delta_table)
        new_desc = ""
        for x in split_desc:
            if x != split_desc[0]:
                new_desc = new_desc + "_____" + x.replace("&amp;", "&")
        self.subreddit.update_settings(description=new_desc)
        logging.debug("Updated top 10 list.")

        ## Section to create and update wiki/leaderboards
##        loggging.debug("Updating wiki leaderboards.")
##        wiki_page = self.reddit.get_wiki_page(self.config.subreddit, leaderboards)
##        self.reddit.edit_wiki_page(self.config.subreddit, user_wiki_page.page, \
##            new_content, "Updated all-time table.")
##        logging.debug("Updated delta tracker leaderboard.")

    # Incorporate this function back into update_top_ten_list() function?
    def get_top_ten_deltas(self):
        """ Get a list of the top 10 delta earners. """
        logging.debug("Retrieving top 10 list.")
        flair_list = [f for f in self.subreddit.get_flair_list(limit=None)]
        flair_list = sorted(flair_list, key=self.get_flair_number)
        flair_list.reverse()
        while len(flair_list) < 10:
            flair_list.append({u'user': u'none', u'flair_text': u'no deltas'})
        return flair_list[0:10]

    # This func is never called?
    def get_flair_number(self, dic):
        """ Get numeric value from flair. """
        try:
            num = int(dic[u'flair_text'].replace(u'∆', u''))
        except ValueError:
            num = None
            print "Viva la infinity!"
        return num

    def multiple_deltas_thread(self, orig_comment):
        """ Did this poster give > 1 delta in this thread? """
        logging.debug("Checking for multiple deltas.")
        comments = self.get_thread_comments(orig_comment)
        if type(comments) is praw.objects.MoreComments:
            comments = comments.comments()
        users = {}
        for comment in comments:
            if comment.author != None:
                if comment.author.name not in users:
                    users[comment.author.name] = 0
                if self.find_delta(comment, False):
                    users[comment.author.name] += 1
        if users[orig_comment.author.name] > 1:
            logging.debug("more than 0 comments in thread")
            return True
        logging.info("somehow got here")
        return False

    def get_thread_comments(self, comment):
        """Returns a list of all comments in a comment's thread.

        Implements a stack to gather a list of all comments in a
        thread in which the original comment is involved.
        """
        logging.debug("Getting all comments in thread.")
        root = self.get_root_comment(comment)
        if root is not None:
            stack = [root]
        else:
            logging.warning("Root was returned as None-Type in function self.get_thread_comments()")
            stack = []
        retval = []
        while stack != []:
            item = stack.pop(0)
            if type(item) is praw.objects.MoreComments:
                try:
                    for comment in item.comments():
                        stack.append(comment)
                except TypeError:
                    if item.comments() is None:
                        logging.warning("MoreComments object was seen as NoneType")
                    else:
                        raise TypeError("item.comments() is of type {0}".format(type(item.comments())))
                continue
            for reply in item.replies:
                if type(reply) is praw.objects.MoreComments:
                    try:
                        new_comments = reply.comments()
                        for comment in new_comments:
                            stack.append(comment)
                    except:
                        logging.debug('item:{0}'.format(item))
                        logging.debug('reply:{0}').format(reply)
                        logging.debug('reply.submission:{0}').format(reply.submission)
                        logging.debug('reply.comments(): {0}').format(reply.comments)

                stack.append(reply)
            retval.append(item)
        return retval

    def get_root_comment(self, comment):
        """ Find and return the root comment for this thread """
        if comment.is_root:
            logging.debug("Comment IS root comment.")
            return comment
        submission = comment.submission
        parent = False
        while not parent:
            for c in submission.comments:
                if self.comment_in_path(c, comment):
                    logging.debug("Root comment found {}.".format(c.body))
                    return c
        return None

    def comment_in_path(self, root, comment):
        """ figure out whether or not comment is in child path of root """
        stack = [root]
        while stack:
            item = stack.pop(0)
            try:
                if not hasattr(item, 'replies'):
                    logging.debug("No attribute .replies, a MoreComment")
                    comments = item.comments()
                    for reply in comments:
                        stack.append(reply)
                        if reply == comment:
                            return True
                for reply in item.replies:
                    stack.append(reply)
                    if reply == comment:
                        return True
            except AttributeError:
                logging.debug("Probably a MoreComments object.")
        return False

    def write_previous_comment_id(self, the_id = 'prev_id.txt'):
        """ Write the previous comment's ID to file. """
        id_file = open(the_id, 'w')
        id_file.write(the_id)
        id_file.close()
        return

    def get_previous_comment_id(self, the_id = 'prev_id.txt'):
        """ Get the last comment's ID from file. """
        try:
            id_file = open(the_id, 'r')
            current = id_file.readline()
            if current == "None":
                current = None
            id_file.close()
            #current_arrayify = ['%s' % current]
            return current
        except IOError:
            logging.warning("\n\nNo ID file. Create it.")
            id_file = open(the_id, 'w+')
            id_file.write("None")
            id_file.close()
            return None

    def message_commands(self):
        """  Checks messages and takes appropriate actions.
        """
        for msg in self.get_unread():
                if msg.author.name not in self.config.mods:
                    msg.mark_as_read()
                    continue
                # Each id needs to be preceded with an asterisk
                if 'ScanThread' in msg.body:
                    thread_ids = splitter(msg.body)
                    for url in thread_ids:
                        logging.debug('scanning {0} thread'.format(url))
                        scan(comments = self.user.get_submission(submission_id = "url").comments)
                    msg.mark_as_read()
                if 'ScanComment' in msg.body:
                    comment_ids = splitter(msg.body)
                    # It would be ideal to pass ids directly onto scan,
                    # unfortunately the t1 header must be appended.
                    for url in comment_ids:
                        logging.debug("scanning u't1_{0}' comment".format(url))
                        scan(comments = [self.user.get_info(thing_id=u't1_{0}'.format(url)),])
                    msg.mark_as_read()
                if 'DeleteDelta' in msg.body:
                    continue
                    # How can this work?

                    #comment_id = splitter(msg.body)
                    #logging.debug("scanning u't1_{0}' comment".format(comment_id))
                    #del_comment = self.user.get_info(thing_id=u't1_{0}'.format(comment_id))
                    #add_points(del_comment.author, num_points=-1)

    def splitter(self, message_body, char = '*'):
        """ str -> lst
        Returns all the urls in a string.
        Precon: urls must be preceded by the char and separated by a space.

        >>> splitter('*1n2k3p 9uaddj')
        ['1n2k3p', '9uaddj']
        """
        return message_body[message_body.find(char)+1:].split()

    def update_delta_tracker(self, comment):
        comment_url = comment.permalink
        comment_submission = comment.submission
        comment_submission_title = comment_submission.title
        comment_submission_url = comment_submission.url
        parent = self.reddit.get_info(thing_id=comment.parent_id)
        parent_author = parent.author.name.lower()
        try:
            user_wiki_page = self.reddit.get_wiki_page(self.config.subreddit, parent_author)
            if user_wiki_page.page == parent_author:
                #this is the parent's wiki page, update it.
                add_link = "\n[%s](%s)" % (comment_submission_title, comment_url)
                new_content = user_wiki_page.content_md + add_link
                self.reddit.edit_wiki_page(self.config.subreddit, user_wiki_page.page, new_content,
                                      "Updated delta links.")
                logging.debug("Updated delta tracker page for %s" % parent_author)
        except:
            #page doesn't exist, create it
            initial_text = "User /u/%s received deltas in the following threads:\n\n" % parent_author
            add_link = "\n* [%s](%s)" % (comment_submission_title, comment_url)
            full_update = initial_text + add_link
            self.reddit.edit_wiki_page(self.config.subreddit, parent_author, full_update,
                                       "Created user's delta links page.")
            logging.info("Created tracker page for %s" % parent_author)
            #Now add link to user's thread to the main page.
            delta_tracker_page = self.reddit.get_wiki_page(self.config.subreddit, "delta_tracker")
            delta_tracker_page_body = delta_tracker_page.content_md
            authors_page = "http://www.reddit.com/r/%s/wiki/%s" % (self.config.subreddit,
                           parent_author)
            new_link = "\n* /u/%s" % (parent_author)
            new_content = delta_tracker_page_body + new_link
            self.reddit.edit_wiki_page(self.config.subreddit, "delta_tracker", new_content,
                                       "Updated tracker page.")
            logging.debug("Updated delta_tracker to link to %s's page" % parent_author)

    def go(self):
        """ Start DeltaBot. """
        logging.info('starting with %0.1fs scan period\n\n' % PERIOD_SCAN)
        before_id = self.get_previous_comment_id()
        #before_id = None
        logging.info("We're starting from this ID: %s\n\n" % before_id)
        temp_id = before_id
        logging.info("Temp id: %s\n Before id: %s" % (temp_id, before_id))
        while True:
            start_time = time.time()
            before_id = self.scan(before_id)
            #NEW -- UPDATE TOP 10 LIST
            self.update_top_ten_list()
            # was there a new comment? if so, write to cache
            if before_id != temp_id:
                self.write_previous_comment_id(before_id)
                temp_id = before_id
            sleep_time = max(0, PERIOD_SCAN - (time.time() - start_time))
            logging.info('sleeping %0.1fs' % sleep_time)
            logging.info("Current ID is %s\n\n" % before_id)
            time.sleep(sleep_time)
