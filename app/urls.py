# Copyright (c) 2008-2010, Joshua Sled <jsled@asynchronous.org>
# See LICENSE file for "New BSD" license details.

from django.conf.urls.defaults import *

urlpatterns = patterns(
    'brewjournal.app.views',
    (r'^$', 'root'),

    (r'^logout/$', 'logout_view'),

    (r'^user/(?P<user_name>[^/]+)/?$', 'user_index'),
    (r'^user/(?P<user_name>[^/]+)/profile/?$', 'user_profile'),
    (r'^user/(?P<user_name>[^/]+)/brew/(?P<brew_id>\d+)(/step/(?P<step_id>\d+))?/?$', 'brew'),
    # /user/jsled/brew/new/?recipe_id=42
    (r'^user/(?P<user_name>[^/]+)/brew/new/?$', 'user_brew_new'),
    (r'^user/(?P<user_name>[^/]+)/brew/(?P<brew_id>\d+)/edit/$', 'brew_edit'),

    (r'^user/(?P<user_name>[^/]+)/brew/(?P<brew_id>\d+)/competition-results/(?P<results_id>new|\d+)$', 'brew_edit_competition_results'),
    (r'^user/(?P<user_name>[^/]+)/brew/(?P<brew_id>\d+)/competition-results/(?P<results_id>\d+)/delete$', 'brew_delete_competition_results'),

    (r'^user/(?P<user_name>[^/]+)/brew/(?P<brew_id>\d+)/competition-results/(?P<results_id>\d+)/scoresheet/(?P<scoresheet_id>new|\d+)$', 'brew_edit_comp_scoresheet'),
    (r'^user/(?P<user_name>[^/]+)/brew/(?P<brew_id>\d+)/competition-results/(?P<results_id>\d+)/scoresheet/(?P<scoresheet_id>\d+)/delete$', 'brew_delete_comp_scoresheet'),

    (r'^user/(?P<user_name>[^/]+)/shopping/?$', 'user_shopping_list'),

    # GET /user/jsled/star?recipe_id=42 + POST
    # GET /user/jsled/star?url=<http://.../recipe> + POST
    (r'^user/(?P<user_name>[^/]+)/star/$', 'user_star'),
    
    # /recipe/new/?clone_from_recipe_id=42
    # /recipe/new/?clone_from_url=<...>
    (r'^recipe/new/$', 'recipe_new'),
    (r'^recipe/(?P<recipe_id>\d+)/(?P<recipe_name>.+)?$', 'recipe'),
    (r'^recipe/$', 'recipe_index'),

    (r'^calc/mash-sparge/$', 'calc_mash_sparge'),

    (r'^500$', 'intentional_500'),
)
