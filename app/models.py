# -*- encoding: utf-8 -*-

# Copyright (c) 2008-2009, Joshua Sled <jsled@asynchronous.org>
# 
# All rights reserved.
# 
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are
# met:
# 
#     * Redistributions of source code must retain the above copyright
#       notice, this list of conditions and the following disclaimer.
# 
#     * Redistributions in binary form must reproduce the above
#       copyright notice, this list of conditions and the following
#       disclaimer in the documentation and/or other materials provided
#       with the distribution.
# 
#     * The names of its contributors may not be used to endorse or promote
#       products derived from this software without specific prior written
#       permission.
# 
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS
# "AS IS" AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT
# LIMITED TO, THE IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR
# A PARTICULAR PURPOSE ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT
# OWNER OR CONTRIBUTORS BE LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL,
# SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT
# LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES; LOSS OF USE,
# DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON ANY
# THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

import datetime
import itertools
import urllib
from decimal import Decimal, Context, ROUND_HALF_UP, InvalidOperation

from django.db import models
from django.contrib import auth

from timezones.fields import TimeZoneField

class StepFilter (object):
    def __init__(self, conditions=None):
        self._conditions = conditions or []

    def eval(self, **kwargs):
        for condition in self._conditions:
            if not condition(**kwargs):
                return False
        return True

class StepType (object):
    def __init__(self, id, label, input_filter, interesting_fields=None, next_steps=None):
        self._id = id
        self._label = label
        self._input_filter = input_filter or StepFilter()
        if not interesting_fields: interesting_fields = []
        if not next_steps: next_steps = []
        self._interesting_fields = interesting_fields
        self._next_steps = next_steps

    id = property(lambda s: s._id)
    label = property(lambda s: s._label)
    interesting_fields = property(lambda s: s._interesting_fields)
    next_steps = property(lambda s: s._next_steps)
    input_filter = property(lambda s: s._input_filter)

    def is_terminal(self):
        return len(self.next_steps) == 0

RecipeTypes = (
    ('e', 'Extract'),
    ('p', 'Partial Mash'),
    ('a', 'All Grain'),
    )

DispenseTypes = (
    ('k', 'kegging'),
    ('b', 'bottling')
    )
    
class UserProfile (models.Model):
    user = models.ForeignKey(auth.models.User, unique=True)

    pref_brew_type = models.CharField(max_length=1, choices=RecipeTypes, default='a')
    pref_make_starter = models.BooleanField(default=False)
    pref_secondary_ferm = models.BooleanField(default=False)
    pref_dispensing_style = models.CharField(max_length=1, choices=DispenseTypes, default='b')

    timezone = TimeZoneField(default='UTC')

    def __getitem__(self, key):
        return self.__dict__.get(key, None)


def filter_user_pref(preference_name, value=True):
    def _foo(**kwargs):
        user = kwargs['user']
        profile = user.get_profile()
        return profile[preference_name] == value
    return _foo

def filter_recipe_type(types):
    def _foo(**kwargs):
        recipe = kwargs['recipe']
        return recipe.type in types
    return _foo

def filter_recipe_is_lager():
    return lambda **kw: True

def filter_recipe_estimated_og_above(val):
    return lambda **kw: True

no_filter = StepFilter()

# Other possible preferences/variants
# -----------------------------------
# practice fwh?
# typical sparge schedule: 1, 2, 3 steps?
# all_grain journal detail level:
#  - low: dough -> sparge -> boil-start
#  - medium: dough -> batch1-start -> batch1-end [-> batchN-start -> batchN-end] -> boil-start
#  - high:

# to get a graph of step relations/dependencies:
#
# ./manage.py shell
# from app import models
# print 'digraph G {';
# for step in models.new_step_types:
#   for next in step.next_steps:
#     print '%s -> %s;' % (step.id.replace('-', '_'), next.replace('-', '_'))
# print '}'
# | dot -Tpng -o step-graph.png -
new_step_types = [ StepType('buy', 'buy ingredients', no_filter, ['time'], ['starter', 'strike', 'steep']),
                   StepType('starter', 'make starter', StepFilter([filter_user_pref('pref_make_starter')]), ['time', 'volume'], ['strike', 'steep']),
                   StepType('strike', 'strike water', StepFilter([filter_recipe_type(['a', 'p'])]), ['volume', 'temp'],  ['dough', 'mash']),
                   StepType('dough', 'dough-in', no_filter, ['volume', 'temp'], ['mash', 'sparge']),
                   StepType('mash', 'mash', no_filter, ['time', 'temp'], ['recirc', 'vorlauf', 'sparge']),
                   StepType('recirc', 'recirculation', no_filter, [], ['vorlauf', 'sparge']),
                   StepType('vorlauf', 'vorlauf', no_filter, ['time'], ['sparge']),
                   StepType('sparge', 'sparge', no_filter, ['volume', 'temp'], ['batch1-start', 'boil-start']),
                   StepType('fwh', 'first wort hopping', no_filter, ['time'], ['batch1-start', 'boil-start']),
                   StepType('batch1-start', '1st runnings, start', no_filter, ['gravity'], ['batch1-end']),
                   StepType('batch1-end', '1st runnings, end', no_filter, ['gravity', 'volume'], ['batch2-start', 'boil-start']),
                   StepType('batch2-start', '2nd runnings, start', no_filter, ['gravity'], ['batch2-end']),
                   StepType('batch2-end', '2nd runnings, end', no_filter, ['gravity', 'volume'], ['batch3-start', 'boil-start']),
                   StepType('batch3-start', '3rd runnings, start', no_filter, ['gravity'], ['batch3-end']),
                   StepType('batch3-end', '3rd runnings, end', no_filter, ['gravity', 'volume'], ['boil-start']),
                   StepType('steep', 'steep', StepFilter([filter_recipe_type(['e', 'p'])]), ['time', 'volume', 'temp'], ['boil-start']),
                   StepType('boil-start', 'boil, start', StepFilter([filter_recipe_type(['e'])]), ['time'], ['boil-add', 'boil-end']),
                   StepType('boil-add', 'boil, addition', no_filter, ['time'], ['boil-add', 'boil-end']),
                   StepType('boil-end', 'boil, end', no_filter, ['time'], ['pitch']),
                   StepType('pitch', 'pitch', no_filter, ['time', 'gravity', 'volume', 'temp'], ['ferm1']),
                   StepType('ferm1', 'primary fermentation', no_filter, ['time', 'gravity', 'temp'], ['sample', 'ferm2', 'ferm-add', 'lager', 'keg', 'bottle', 'aging']),
                   StepType('ferm2', 'secondary fermentation', StepFilter([filter_user_pref('pref_secondary_ferm')]), ['time', 'gravity', 'temp'],
                            ['sample', 'ferm-add', 'lager', 'keg', 'bottle', 'aging']),
                   StepType('sample', 'gravity sample', no_filter, ['gravity'],
                            ['ferm-add', 'ferm2', 'sample','lager', 'keg', 'bottle', 'aging']),
                   StepType('ferm-add', 'addition', no_filter, ['time'], ['sample', 'ferm-add', 'lager', 'keg', 'bottle', 'aging']),
                   StepType('lager', 'lagering', StepFilter([filter_recipe_is_lager()]), ['time', 'temp'], ['sample', 'condition', 'keg', 'bottle', 'aging']),
                   StepType('condition', 'conditioning', no_filter, ['time', 'temp'], ['keg', 'bottle', 'aging']),
                   StepType('keg', 'kegged', StepFilter([filter_user_pref('pref_dispensing_style', 'k')]), ['time', 'temp', 'gravity'], ['consumed']),
                   StepType('bottle', 'bottled', StepFilter([filter_user_pref('pref_dispensing_style', 'b')]), ['time'], ['consumed']),
                   StepType('aging', 'aging', StepFilter([filter_recipe_estimated_og_above(Decimal('1.100'))]), [], ['keg', 'bottle']),
                   StepType('consumed', 'consumed', no_filter, [], []),
               ]

step_types_by_id = dict([(type.id, type) for type in new_step_types])
step_types_ui_choices = [(type.id, type.label) for type in new_step_types]

def flatten(*args):
    rtn = []
    for arg in args:
        rtn.extend(arg)
    return rtn


Weight_Units = [
    ('gr', 'grams'),
    ('kg', 'kilograms'),
    ('oz', 'ounces'),
    ('lb', 'pounds'),
    ('ct', 'count'),
    ]

Volume_Units = [
    ('fl', 'fluid ounces'),
    ('c', 'cups'),
    ('q', 'quarts'),
    ('gl', 'gallons'),
    ('ml', 'milliliters'),
    ('l', 'liters'),
    ('ct', 'count'),
    ('tsp', 'teaspoon'),
    ('tbsp', 'tablespoon'),
    ('pt', 'pint')
    ]

Temp_Units = [
    ('f', 'Farenheit'),
    ('c', 'Celsius')
    ]

All_Units = flatten(Weight_Units, Volume_Units)

class Style (models.Model):
    name = models.CharField(max_length=100)
    bjcp_code = models.CharField(max_length=8)
    parent = models.ForeignKey('self', null=True)

    def __str__(self):
        return self.__unicode__()
    
    def __unicode__(self):
        return u'%(name)s %(bjcp_code)s' % self.__dict__


class Grain (models.Model):
    name = models.CharField(max_length=200)
    extract_min = models.SmallIntegerField(null=True)
    extract_max = models.SmallIntegerField(null=True)
    liter_potential_min = models.SmallIntegerField(null=True)
    liter_potential_max = models.SmallIntegerField(null=True)
    lovibond_min = models.SmallIntegerField(null=True)
    lovibond_max = models.SmallIntegerField(null=True)
    description = models.CharField(max_length=200)
    group = models.CharField(max_length=8)

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return u'%(name)s' % self.__dict__


class Hop (models.Model):
    name = models.CharField(max_length=100)
    aau_low = models.DecimalField(max_digits=3, decimal_places=1)
    aau_high = models.DecimalField(max_digits=3, decimal_places=1)

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return u'%(name)s' % self.__dict__


class Adjunct (models.Model):
    name = models.CharField(max_length=100)
    group = models.CharField(max_length=30)

    def __unicode__(self):
        return u'%s (%s)' % (self.name, self.group)


class YeastManufacturer (models.Model):
    name = models.CharField(max_length=100)

    def __unicode__(self):
        return u'%(name)s' % self.__dict__


class Yeast (models.Model):
    Types = [
        ('ale', 'Ale'),
        ('belgian', 'Belgian'),
        ('brett', 'Brettanomyces'),
        ('lager', 'Lager'),
        ('lambic', 'Lambic'),
        ('wine', 'Wine'),
        ('mead', 'Mead'),
        ('cider', 'Cider'),
        ('weird', 'Speciality'),
        ]
    manufacturer = models.ForeignKey(YeastManufacturer)
    ident = models.CharField(max_length=10)
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=1000, blank=True)
    type = models.CharField(max_length=7, choices=Types)

    # @fixme: attenuation; min/max temp; URL; class
    #Flocc_Types = ['low', 'medium-low', 'medium', 'medium-high', 'high']
    #flocculation = models.CharField(max_length=10, choices=Floc_Types)
    #attenuation_low = models.IntegerField()
    #attenuation_high = models.IntegerField()
    #temp_low = models.IntegerField()
    #temp_high = models.IntegerField()
    #alc_tolerance = models.DecimalField(max_digits=3, decimal_places=1)

    def __unicode__(self):
        return u'%s %s: %s' % (self.manufacturer.name, self.ident, self.name)


class Recipe (models.Model):
    author = models.ForeignKey(auth.models.User)
    name = models.CharField(max_length=200)
    insert_date = models.DateTimeField(default=datetime.datetime.now)
    batch_size = models.DecimalField(max_digits=4, decimal_places=2)
    batch_size_units = models.CharField(max_length=4, choices = Volume_Units, default='gl')
    style = models.ForeignKey(Style, null=True)
    derived_from_recipe = models.ForeignKey('self', null=True, blank=True)
    type = models.CharField(max_length=1, choices=RecipeTypes, default='a')
    source_url = models.URLField(max_length=300, blank=True, null=True, verify_exists=True)
    notes = models.TextField(null=True, blank=True)

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return u'%(name)s - %(style)s %(batch_size)s' % {'name': self.name,
                                                         'style': self.style,
                                                         'batch_size': self.batch_size}

    def url(self):
        return u'/recipe/%d/%s' % (self.id, self.name)


class RecipeGrain (models.Model):
    recipe = models.ForeignKey(Recipe)
    grain = models.ForeignKey(Grain)
    amount_value = models.DecimalField(max_digits=4, decimal_places=2)
    amount_units = models.CharField(max_length=2, choices=All_Units, default='lb')


class RecipeHop (models.Model):
    recipe = models.ForeignKey(Recipe)
    hop = models.ForeignKey(Hop)
    amount_value = models.DecimalField(max_digits=4, decimal_places=2)
    amount_units = models.CharField(max_length=2, choices=Weight_Units)
    boil_time = models.SmallIntegerField()


class RecipeYeast (models.Model):
    recipe = models.ForeignKey(Recipe)
    yeast = models.ForeignKey(Yeast)
    ideal = models.BooleanField(default=True)


class RecipeAdjunct (models.Model):
    recipe = models.ForeignKey(Recipe)
    adjunct = models.ForeignKey(Adjunct)
    amount_value = models.DecimalField(max_digits=5, decimal_places=2)
    amount_units = models.CharField(max_length=4, choices=All_Units)
    boil_time = models.SmallIntegerField()
    notes = models.CharField(max_length=300, null=True, blank=True)


class StarredRecipe (models.Model):
    '''
    A Recipe a User has specifically called out (to be turned into a Brew, or whatever).
    '''
    recipe = models.ForeignKey(Recipe)
    user = models.ForeignKey(auth.models.User)
    when = models.DateTimeField(default=datetime.datetime.now)
    notes = models.CharField(max_length=1000, blank=True, default='')


class BrewManager (models.Manager):
    def brews_with_future_steps(self, user):
        brew_ids = [step.brew_id for step in Step.objects.future_steps_for_user(user)]
        return Brew.objects.filter(id__in=brew_ids)

    def brews_pre_brew(self, user):
        # @fixme: if the brew date is in the future, too?
        future_brews = Brew.objects.brews_with_future_steps(user)
        def pre_brew(brew):
            future_steps = brew.future_steps()
            # @fixme, this should probably be step.is_pre_brew() or something.
            substeps = [step for step in future_steps if step.type in ['buy', 'strike', 'steep']]
            return len(substeps) > 0
        pre_brews = [brew for brew in future_brews if pre_brew(brew)]
        return pre_brews
        

class Brew (models.Model):
    # recipe_name = models.CharField(max_length=500)
    brew_date = models.DateTimeField('brew date', null=True, blank=True, default=datetime.datetime.now)
    brewer = models.ForeignKey(auth.models.User)
    notes = models.TextField(null=True, blank=True)
    recipe = models.ForeignKey(Recipe, null=True)
    last_update_date = models.DateTimeField(null=True, editable=False)
    last_state = models.CharField(max_length=30, choices=step_types_ui_choices, null=True, editable=False)
    is_done = models.BooleanField(editable=False, default=False)

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return u'%s (%s)' % (self.recipe.name, self.brewer.username)

    objects = BrewManager()

    class Meta:
        ordering = ['brew_date', 'last_update_date']
    
    def update_from_steps(self, steps = None):
        '''
        Based on the type and timestamp of the latest step of `steps`, update the state of the Brew.
        It's the caller's responsibility to save the updated object.
        '''
        # only allow non-future steps to update state.
        past_steps = [step for step in steps if not step.in_future()] or []
        if len(past_steps) > 0:
            last_step = past_steps[-1]
            self.last_update_date = last_step.date
            self.last_state = last_step.type
            self.is_done = step_types_by_id[last_step.type].is_terminal()
            if not self.brew_date:
                # @fixme; this could be better, taking the first actually-brewing-related step, rather than just index=0.
                # @fixme: then, get "is_actually_brewing_related" into StepTypes model
                self.brew_date = past_steps[0].date
        else:
            self.brew_date = None
            self.last_update_date = None
            self.last_state =  None
            self.is_done = False

    def next_steps(self):
        gennie = NextStepGenerator(self)
        return gennie.get_next_steps()
    
    def future_steps(self):
        return [step for step in self.step_set.all() if step.in_future()]

    def title(self):
        if not self.recipe:
            return "unnamed"
        return self.recipe.name


class StepManager (models.Manager):
    def future_steps_for_user(self, user):
        now = datetime.datetime.now()
        return Step.objects.filter(brew__brewer__exact=user, date__gt=now)


class Step (models.Model):
    '''
    Individual steps/events/readings/samples associated with the brew instance.
    '''
    brew = models.ForeignKey(Brew)
    type = models.CharField(max_length=30, choices=step_types_ui_choices)
    date = models.DateTimeField()
    entry_date = models.DateTimeField(editable=False, default=datetime.datetime.now)

    volume = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    volume_units = models.CharField(max_length=4, null=True, blank=True, choices = Volume_Units, default='gl')

    temp = models.IntegerField(null=True, blank=True)
    temp_units = models.CharField(max_length=1, null=True, blank=True, choices = Temp_Units, default='f')

    # gravity = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    gravity_read = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    gravity_read_temp = models.IntegerField(null=True, blank=True)
    gravity_read_temp_units = models.CharField(max_length=1, null=True, blank=True, choices = Temp_Units, default='f')

    notes = models.CharField(max_length=500, blank=True)

    def _get_gravity(self):
        if not self.gravity_read or not self.gravity_read_temp:
            return None
        temp = self.gravity_read_temp
        if self.gravity_read_temp_units == 'c':
            temp = celsius_to_farenheit(self.gravity_read_temp)
        return correct_gravity(self.gravity_read, temp)

    def _set_gravity(self, gravity):
        self.gravity_read = gravity
        self.gravity_read_temp = 59
        self.gravity_read_temp_units = 'f'

    gravity = property(_get_gravity, _set_gravity)

    def __str__(self):
        return self.__unicode__()

    def __unicode__(self):
        return u'[%s:%s:%s] vol=%s, temp=%s, gravity=%s, notes [%s]' % (self.brew.recipe.name, self.date.strftime('%x %X'), self.type, self.volume, self.temp, self.gravity, self.notes)

    def in_future(self):
        # @fixme: inject datetime.datetime for testability
        return self.date > datetime.datetime.now()

    objects = StepManager()

    class Meta:
        ordering = ['date']


class NextStep (object):
    def __init__(self, type, date, existing_step=None):
        self.type = type
        self.date = date
        self.existing_step = existing_step

    def __unicode__(self):
        existing_part = u''
        if self.existing_step:
            existing_part = ' (existing id %d)' % (self.existing_step.id)
        date_part = u''
        if self.date:
            date_part = u' @ %s' % (self.date)
        return u'[%s%s%s]' % (self.type.id, date_part, existing_part)

    def __str__(self):
        return self.__unicode__()


class NextSteps (object):
    def __init__(self, possible=None, maybe=None):
        self.possible = possible or []
        self.maybe = maybe or []

    def __unicode__(self):
        return u'possible: %s, maybe: %s' % ([str(x) for x in self.possible],
                                             [str(x) for x in self.maybe])

    def __str__(self):
        return self.__unicode__()


class NextStepGenerator (object):
    '''
    Encapsulate the process of getting the next-step structure from a brew, user, prefs, &c.
    '''
    def __init__(self, brew, **kwargs):
        self._brew = brew
        self._user = kwargs.get('user', brew.brewer)
        self._recipe = brew.recipe

    def get_next_steps(self):
        next_steps = NextSteps()
        to_try = []
        last_date = None
        if self._brew.last_state:
            last_step_type = step_types_by_id[self._brew.last_state]
            try:
                last_step = [s for s in self._brew.step_set.all() if s.type == self._brew.last_state][0]
            except Exception,e:
                print 'brew,last_state,steps',self._brew,self._brew.last_state,self._brew.step_set.all()
                raise
            # @fixme: assert(last_step is not None)
            last_date = last_step.date
            to_try.extend(last_step_type.next_steps)
        else:
            # @fixme: get these from StepTypes themselves
            to_try.extend(['starter', 'strike', 'steep', 'boil-start'])
        future_steps = [step for step in self._brew.step_set.all() if step.in_future()]
        for typeid in to_try:
            steptype = step_types_by_id[typeid]
            appropriate_list = None
            if steptype.input_filter.eval(brew=self._brew, user=self._user, recipe=self._recipe):
                appropriate_list = next_steps.possible
            else:
                appropriate_list = next_steps.maybe
            #
            existing_step = None
            next_step_date = last_date
            matching_future_steps = [step for step in future_steps if step.type == typeid]
            if len(matching_future_steps) > 0:
                existing_step = matching_future_steps[0]
                if not next_step_date or existing_step.date > next_step_date:
                    next_step_date = existing_step.date
            #
            next_step = NextStep(steptype, next_step_date, existing_step)
            appropriate_list.append(next_step)
        return next_steps
       

class ShoppingList (object):
    '''
    Find a user's pre-brews with a future "buy-ingredients" step, and consolidates the ingredients by type

    Each ingredient type is a list of (Ingredient,[(RecipeIngredient,Brew)])

    E.g., Grains -> (Centenniel, [ (5oz,Brew#42), (2oz,Brew#43), ...])
    
    ''' # '
    
    def __init__(self, user=None, **kwargs):
        self._grains = {}
        self._hops = {}
        self._adjuncts = {}
        self._yeasts = {}

        pre_brews = kwargs.get('pre_brews', None)
        if not pre_brews:
            now = datetime.datetime.now()
            future_buy_steps = Step.objects.filter(brew__brewer__exact=user, date__gt=now, type='buy')
            future_buy_brews = [step.brew.id for step in future_buy_steps]
            pre_brews = Brew.objects.filter(id__in=future_buy_brews)
        self._aggregate_brews(pre_brews)

    def shopping_to_do(self):
        to_buy_count = len(self._grains) + len(self._hops) + len(self._adjuncts) + len(self._yeasts)
        return to_buy_count > 0

    def _get_grains(self):
        return [(grain,brews) for grain,brews in self._grains.iteritems()]
    grains = property(_get_grains)

    def _get_hops(self):
        return [(hop,brews) for hop,brews in self._hops.iteritems()]
    hops = property(_get_hops)

    def _get_adjuncts(self):
        return [(adjunct,brews) for adjunct,brews in self._adjuncts.iteritems()]
    adjuncts = property(_get_adjuncts)

    def _get_yeasts(self):
        return [(yeast,brews) for yeast,brews in self._yeasts.iteritems()]
    yeasts = property(_get_yeasts)
    
    def _aggregate_brews(self, pre_brews):
        for brew in pre_brews:
            recipe = brew.recipe
            if not recipe:
                continue
            for collection, recipe_item_getter, item_type_getter in \
                    [(self._grains, lambda: recipe.recipegrain_set.all(), lambda x: x.grain),
                     (self._hops, lambda: recipe.recipehop_set.all(), lambda x: x.hop),
                     (self._adjuncts, lambda: recipe.recipeadjunct_set.all(), lambda x: x.adjunct),
                     (self._yeasts, lambda: recipe.recipeyeast_set.all(), lambda x: x.yeast)]:
                for recipe_item in recipe_item_getter():
                    item = item_type_getter(recipe_item)
                    collection.setdefault(item, []).append((recipe_item,brew))


class TimeConst:
    SECOND = 1000
    MINUTE = 60 * SECOND
    HOUR = 60 * MINUTE
    DAY = 24 * HOUR
    WEEK = 7 * DAY
    
def celsius_to_farenheit(temp):
    '''
    >>> print celsius_to_farenheit(0.0)
    32.00
    >>> print celsius_to_farenheit(100.0)
    212.00
    >>> print celsius_to_farenheit(-17.78)
    -0.004
    >>> print celsius_to_farenheit(-40)
    -40.0
    '''
    temp = str(temp)
    if temp.lstrip('-').find('.') == -1:
        temp = temp + '.'
    parts = temp.split('.')
    prec = len(parts[0]) + len(parts[1])
    context = Context(prec=prec)
    _1_8 = context.create_decimal('1.8')
    _32 = context.create_decimal('32.')
    temp = context.create_decimal(temp)
    return _1_8 * temp + _32

_c1 = Decimal('1.313454')
_c2 = Decimal('0.132674')
_c3 = Decimal('0.002057793')
_c4 = Decimal('0.000002627634')
_adj = Decimal('0.001')
def correct_gravity(gravity, temp_f):
    '''
    All temperatures are in expressed in degrees F.

    correction = 1.313454 - 0.132674*F + 0.002057793*F*F - 0.000002627634*F*F*F

    SG_corrected = SG + (correction * 0.001)
    - http://www.primetab.com/formulas.html
    - agrees with http://brewery.org/library/HydromCorr0992.html


    >>> print correct_gravity(1.042, 108)
    1.050
    >>> print correct_gravity(1.050, 82)
    1.053
    >>> print correct_gravity(1.0123103856, 59)
    1.012
    >>> print correct_gravity(1.070, 41)
    1.069
    '''
    gravity = Decimal(str(gravity))
    F = Decimal(str(temp_f))
    ctx = Context(prec=4, rounding=ROUND_HALF_UP)
    gravity = gravity + (_c1 - _c2 * F + _c3 * F * F - _c4 * F * F *  F) * _adj
    return ctx.create_decimal(gravity)


def convert_volume(volume, from_units, to_units):
    ctx = Context(prec=5)
    volume = ctx.create_decimal(volume)

    def simplify_volume(units):
        factor = ctx.create_decimal('1')
        if units == 'fl':
            factor *= ctx.create_decimal('0.125')
            units = 'c'
        if units == 'c':
            factor *= ctx.create_decimal('0.25')
            units = 'q'
        if units == 'q':
            factor *= ctx.create_decimal('0.25')
            units = 'gl'
        if units == 'ml':
            factor *= ctx.create_decimal('0.001')
            units = 'l'
        return (units, factor)
        
    from_units,from_factor = simplify_volume(from_units)
    to_units,to_factor = simplify_volume(to_units)
    inv_to_factor = ctx.create_decimal('1') / to_factor

    conversion_from_to = {
        'l': {'l': ctx.create_decimal('1'),
              'gl': ctx.create_decimal('0.264172052')},
        'gl': {'l': ctx.create_decimal('3.78541178'),
               'gl': ctx.create_decimal('1')},
        }
    return volume * from_factor * conversion_from_to[from_units][to_units] * inv_to_factor


def convert_weight(amount, from_units, to_units):
    '''
    >> print convert_weight(1, 'lb', 'kg')
    0.4539237
    >>> print convert_weight(1, 'kg', 'lb')
    2.20462500000
    >>> print convert_weight(16, 'oz', 'lb')
    1.0000
    >>> print convert_weight(32, 'oz', 'lb')
    2.0000
    >>> print convert_weight(1500, 'gr', 'lb')
    3.30693750000
    >>> print convert_weight(5, 'tsp', 'gr')
    15
    '''
    ctx = Context(prec=6)
    conversion_from_to = {
        'gr': {'gr': ctx.create_decimal('1'),
               'oz': ctx.create_decimal('0.0352739619')},
        'oz': {'gr': ctx.create_decimal('28.35'),
               'oz': ctx.create_decimal('1')},
        }

    def simplify_units(unit):
        factor = ctx.create_decimal('1')
        if unit == 'kg':
            factor = factor * ctx.create_decimal('1000')
            unit = 'gr'
        if unit == 'lb':
            factor = factor * ctx.create_decimal('16')
            unit = 'oz'
        if unit == 'tbsp':
            factor = factor * ctx.create_decimal('3')
            unit = 'tsp'
        if unit == 'tsp':
            factor = factor * ctx.create_decimal('3')
            unit = 'gr'
        if unit == 'pint':
            factor = factor * ctx.create_decimal('910')
            unit = 'gr'
        return (unit,factor)
    
    from_units,from_factor = simplify_units(from_units)
    to_units,to_factor = simplify_units(to_units)
    inv_to_factor = ctx.create_decimal('1') / to_factor
    
    return amount * from_factor * conversion_from_to[from_units][to_units] * inv_to_factor


class BrewDerivations (object):
    def __init__(self, brew):
        self._brew = brew

    def _get_sorted_steps(self, allowable_step_types_sorted):
        allowable_types = dict([(type,idx)
                                for type,idx
                                in itertools.izip(allowable_step_types_sorted,itertools.count())])
        steps = self._brew.step_set.all()
        steps = [step for step in steps
                    if allowable_types.has_key(step.type)]
        steps.sort(lambda a,b: allowable_types[a.type] - allowable_types[b.type])
        return steps

    efficiency_needed_steps = ['boil-start', 'sparge', 'pitch']
    def _get_efficiency_steps(self):
        related_steps = self._get_sorted_steps(BrewDerivations.efficiency_needed_steps)
        related_steps = [step for step in related_steps if step.volume and step.gravity]
        return related_steps
    
    def can_not_derive_efficiency(self):
        '''@return A list of Strings describing what needs to be provided, or [] if we can perform the op'''
        rtn = []
        required = self._get_efficiency_steps()
        if len(required) == 0:
            rtn.append('need one step of of type %s with gravity and volume' % (BrewDerivations.efficiency_needed_steps))
        recipe_grains = self._brew.recipe.recipegrain_set.all()
        if len(recipe_grains) == 0:
            rtn.append('need grains on recipe')
        return rtn

    def efficiency(self):
        related_steps = self._get_efficiency_steps()
        if len(related_steps) == 0:
            raise Exception('assertion violation')
        best_step = related_steps[0]
        ctx = Context(prec=3, rounding=ROUND_HALF_UP)
        potential_points = ctx.create_decimal('0')
        for recipe_grain in self._brew.recipe.recipegrain_set.all():
            grain = recipe_grain.grain
            min,max = tuple([ctx.create_decimal(str(x - 1000)) for x in [grain.extract_min,grain.extract_max]])
            grain_potential_per_lb = (min + max) / ctx.create_decimal('2')
            grain_in_lbs = convert_weight(recipe_grain.amount_value, recipe_grain.amount_units, 'lb')
            recipe_grain_potential = grain_potential_per_lb * grain_in_lbs
            potential_points += recipe_grain_potential
        volume_in_gallons = convert_volume(best_step.volume, best_step.volume_units, 'gl')
        grav = ((best_step.gravity - ctx.create_decimal('1')) * ctx.create_decimal('1000'))
        obtained_points = grav * volume_in_gallons
        efficiency = (obtained_points / potential_points) * ctx.create_decimal('100')
        return efficiency

    abv_start_steps = ['pitch', 'boil-end', 'boil-start']
    abv_end_steps = ['consumed', 'aging', 'bottle', 'keg', 'condition', 'lager', 'ferm-add', 'sample', 'ferm2', 'ferm1']
    def _get_abv_steps(self):
        starting_steps = self._get_sorted_steps(BrewDerivations.abv_start_steps)
        starting_steps = [step for step in starting_steps if step.gravity]
        ending_steps = self._get_sorted_steps(BrewDerivations.abv_end_steps)
        ending_steps = [step for step in ending_steps if step.gravity]
        return starting_steps,ending_steps

    def can_not_derive_abv(self):
        starting_steps,ending_steps = self._get_abv_steps()
        rtn = []
        if len(starting_steps) == 0:
            rtn.append('need a starting-gravity step of type %s with gravity reading' % (BrewDerivations.abv_start_steps))
        if len(ending_steps) == 0:
            rtn.append('need a ending-gravity step of type %s with gravity reading' % (BrewDerivations.abv_end_steps))
        return rtn

    def alcohol_by_volume(self):
        starting_steps,ending_steps = self._get_abv_steps()
        best_start = starting_steps[0]
        best_end = ending_steps[0]
        return (best_start.gravity - best_end.gravity) * Decimal('135')

    def can_not_derive_aa(self):
        return self.can_not_derive_abv()

    def apparent_attenuation(self):
        starting_steps,ending_steps = self._get_abv_steps()
        best_start = starting_steps[0]
        best_end = ending_steps[0]
        fraction_attenuated = (best_end.gravity - Decimal('1.0')) / (best_start.gravity - Decimal('1.0'))
        aa = (Decimal('1.0') - fraction_attenuated) * Decimal('100')
        return aa


class PerHopIbu (object):
    def __init__(self, recipe_hop, low_ibu, high_ibu, percentage=None):
        self._recipe_hop = recipe_hop
        self._low_ibu = low_ibu
        self._high_ibu = high_ibu
        self._percentage = percentage

    recipe_hop = property(lambda s: s._recipe_hop)
    low_ibu = property(lambda s: s._low_ibu)
    high_ibu = property(lambda s: s._high_ibu)

    def _set_pctg(self, x):
        self._percentage = x

    percentage = property(lambda s: s._percentage, _set_pctg)


class IbuDerivation (object):
    def __init__(self, low_ibu, high_ibu, per_hop):
        self._low_ibu = low_ibu
        self._high_ibu = high_ibu
        self._per_hop = per_hop or []

    low = property(lambda s: s._low_ibu)
    high = property(lambda s: s._high_ibu)
    average = property(lambda s: (s._low_ibu + s._high_ibu) / Decimal('2'))
    per_hop = property(lambda s: s._per_hop)


class PerGrainOg (object):
    def __init__(self, recipe_grain, low_og, high_og, percentage=None):
        self._recipe_grain = recipe_grain
        self._low_og = low_og
        self._high_og = high_og
        self._percentage = percentage

    recipe_grain = property(lambda s: s._recipe_grain)
    low_og = property(lambda s: s._low_og)
    high_og = property(lambda s: s._high_og)

    def _set_pctg(self, x):
        self._percentage = x

    percentage = property(lambda s: s._percentage, _set_pctg)


class OgDerivation (object):
    def __init__(self, low_og, high_og, per_grain):
        self._low_og = low_og
        self._high_og = high_og
        self._per_grain = per_grain or []
        
    low = property(lambda s: s._low_og)
    high = property(lambda s: s._high_og)
    average = property(lambda s: (s._low_og + s._high_og) / Decimal('2'))
    per_grain = property(lambda s: s._per_grain)


class PerGrainSrm (object):
    def __init__(self, recipe_grain, low_srm, high_srm, percentage=None):
        self._recipe_grain = recipe_grain
        self._low_srm = low_srm
        self._high_srm = high_srm
        self._percentage = percentage

    recipe_grain = property(lambda s: s._recipe_grain)
    low_srm = property(lambda s: s._low_srm)
    high_srm = property(lambda s: s._high_srm)

    def _set_pctg(self, x):
        self._percentage = x

    percentage = property(lambda s: s._percentage, _set_pctg)


class SrmDerivation (object):
    def __init__(self, low_srm, high_srm, per_grain):
        self._low_srm = low_srm
        self._high_srm = high_srm
        self._per_grain = per_grain or []
        
    low = property(lambda s: s._low_srm)
    high = property(lambda s: s._high_srm)
    average = property(lambda s: (s._low_srm + s._high_srm) / Decimal('2'))
    per_grain = property(lambda s: s._per_grain)


class NumberRange:
    def __init__(self, lo, hi, avg=None):
        self.lo = lo
        self.hi = hi
        self.avg = avg


class RecipeDerivations (object):
    def __init__(self, recipe):
        self._recipe = recipe

    default_efficiency = Decimal('0.75')

    def _test_batch_size_deriv(self, reasons):
        has_batch_size = False
        has_non_zero_batch_size = False
        try:
            if self._recipe.batch_size is not None and self._recipe.batch_size_units is not None:
                has_batch_size = True
            if self._recipe.batch_size > 0:
                has_non_zero_batch_size = True
        except AttributeError,e:
            pass
        if not has_batch_size:
            reasons.append('recipe must have batch size and units')
        if not has_non_zero_batch_size:
            reasons.append('recipe must have non-zero batch size')

    def _test_grains_deriv(self, reasons):
        has_grains = False
        try:
            if self._recipe.recipegrain_set and self._recipe.recipegrain_set.count() > 0:
                has_grains = True
        except AttributeError,e:
            pass
        if not has_grains:
            reasons.append('recipe must have grains')

    def _test_hops_deriv(self, reasons):
        has_hops = False
        try:
            if self._recipe.recipehop_set.count() > 0:
                has_hops = True
        except AttributeError,e:
            pass
        if not has_hops:
            reasons.append('recipe must have hops')

    def can_not_derive_og(self):
        '''@return a list of string reasons why we cannot compute an original gravity'''
        reasons = []
        self._test_batch_size_deriv(reasons)
        self._test_grains_deriv(reasons)
        return reasons

    def compute_og(self, efficiency=None):
        '''@return OgDerivation'''
        default_grain_efficiency = efficiency or RecipeDerivations.default_efficiency
        batch_gallons = convert_volume(self._recipe.batch_size, self._recipe.batch_size_units, 'gl')
        accum = NumberRange(Decimal('0'),Decimal('0'))
        def convert_to_gravity(val, batch_gallons):
            return Decimal('1') + ((val / batch_gallons) / Decimal('1000'))
        per_grain = []
        for grain in self._recipe.recipegrain_set.all():
            fermentable_efficiency = Decimal('1')
            if grain.amount_units in [x[0] for x in Weight_Units]:
                try:
                    weight = convert_weight(grain.amount_value, grain.amount_units, 'lb')
                except:
                    # @fixme: log the error or something
                    weight = 0
                normalized_units = weight
                #
                fermentable_efficiency = default_grain_efficiency
                if grain.grain.name.find('Extract') != -1:
                    fermentable_efficiency = Decimal('1')
                #
                norm_units_potential = NumberRange(grain.grain.extract_min, grain.grain.extract_max)
            elif grain.amount_units in [x[0] for x in Volume_Units]:
                try:
                    vol = convert_volume(grain.amount_value, grain.amount_units, 'l')
                except:
                    # @fixme: log or something
                    vol = 0
                normalized_units = vol
                # efficency is always 1 ... ? not really, but lets
                # assume that volume-specified fermentable are
                # extracts or fruit, which is efficient. @fixme
                norm_units_potential = NumberRange(grain.grain.liter_potential_min, grain.grain.liter_potential_max)
            lo,hi = tuple([(Decimal(str(extract)) - Decimal('1000'))
                           * normalized_units
                           * fermentable_efficiency
                           for extract in (norm_units_potential.lo,norm_units_potential.hi)])
            accum.lo += lo
            accum.hi += hi
            lo_gravity = convert_to_gravity(lo, batch_gallons)
            hi_gravity = convert_to_gravity(hi, batch_gallons)
            per_grain.append(PerGrainOg(grain, lo_gravity, hi_gravity))
        low = convert_to_gravity(accum.lo, batch_gallons)
        high = convert_to_gravity(accum.hi, batch_gallons)
        # we want to use these funny 'calc' versions because 1.040/1.080 = 0.966, but 0.040/0.080 = 0.50:
        high_calc = high - Decimal('1')
        for grain in per_grain:
            grain_calc = grain.high_og - Decimal('1')
            grain.percentage = (grain_calc / high_calc) * Decimal('100')
        return OgDerivation(low, high, per_grain)

    def can_not_derive_ibu(self):
        reasons = []
        self._test_batch_size_deriv(reasons)
        self._test_hops_deriv(reasons)
        try:
            Decimal('2') ** Decimal('0.1')
        except InvalidOperation:
            reasons.append('dreamhost has an outdated python that prevents us from computing IBU')
        return reasons

    def compute_ibu(self, gravity=None):
        '''@see http://www.homebrewtalk.com/f128/estimating-bitterness-algorithms-state-art-109681/'''
        if not gravity:
            gravity = self.compute_og().average
        return self.compute_ibu_tinseth(gravity)

    def compute_ibu_tinseth(self, gravity):
        '''
        http://www.rooftopbrew.net/ibu.php
        
        http://www.howtobrew.com/section1/chapter5-5.html
        
        IBU = (1.65 × 0.000125^(G_{gravity} - 1)) × ((1 - e^{-0.04 × t_{min}})/4.1) × ((AAU%/100 × W_{g} × 10) / V_{l})
        '''
        def dec(x):
            return Decimal(x)

        wort_volume = convert_volume(self._recipe.batch_size, self._recipe.batch_size_units, 'l')
        low_accum = dec('0')
        high_accum = dec('0')
        per_hop = []
        for hop in self._recipe.recipehop_set.all():
            weight = convert_weight(dec(hop.amount_value), hop.amount_units, 'gr')
            gravity_exponent = gravity - dec('1.000')
            term1 = dec('1.65') * dec('0.000125') ** gravity_exponent
            term2 = (dec('1') - (dec('-0.04') * dec(str(hop.boil_time))).exp()) / dec('4.1')
            term3_low,term3_high = tuple([(dec(aau) * weight * dec(10)) / wort_volume for aau in (hop.hop.aau_low, hop.hop.aau_high)])
            low = term1 * term2 * term3_low
            high = term1 * term2 * term3_high
            low_accum += low
            high_accum += high
            per_hop.append(PerHopIbu(hop, low, high))
        for hop_ibus in per_hop:
            hop_ibus.percentage = (hop_ibus.high_ibu / high_accum) * Decimal('100')
        return IbuDerivation(low_accum, high_accum, per_hop)

    def can_not_derive_srm(self):
        reasons = []
        self._test_batch_size_deriv(reasons)
        self._test_grains_deriv(reasons)
        return reasons

    def compute_srm(self, efficiency=None):
        return self.compute_srm_morey()

    def compute_srm_morey(self):
        '''
        http://www.beersmith.com/blog/2008/04/29/beer-color-understanding-srm-lovibond-and-ebc/
        http://brewingtechniques.com/brewingtechniques/beerslaw/morey.html
        http://www.homebrewtalk.com/f12/srm-calculations-promash-64792/
        '''

        def dec(x):
            return Decimal(str(x))

        batch_gallons = convert_volume(self._recipe.batch_size, self._recipe.batch_size_units, 'gl')
        lo_accum = dec(0)
        hi_accum = dec(0)
        per_grain = []
        for grain in self._recipe.recipegrain_set.all():
            try:
                weight = convert_weight(grain.amount_value, grain.amount_units, 'lb')
            except:
                # log this
                weight = 0
            lo_mcu,hi_mcu = tuple([(dec(lovibond) * Decimal('0.1') * weight) / batch_gallons
                                   for lovibond in (grain.grain.lovibond_min,grain.grain.lovibond_max)])
            lo,hi = tuple([dec('1.4922') * (mcu ** dec('0.6859')) for mcu in [lo_mcu,hi_mcu]])
            # lo,hi = tuple([(mcu * dec('0.3')) + dec('4.7') for mcu in [lo_mcu,hi_mcu]])
            # lo,hi = tuple([(mcu * dec('0.2')) + dec('8.4') for mcu in [lo_mcu,hi_mcu]])
            lo_accum += lo
            hi_accum += hi
            per_grain.append(PerGrainSrm(grain, lo, hi))
        for grain in per_grain:
            grain.percentage = (grain.high_srm / hi_accum) * Decimal('100')
        low,high = lo_accum,hi_accum
        return SrmDerivation(low, high, per_grain)

    # def compute_og_ibu_srm_matrix(self, efficiency=None):
    #     ''' return a 2x(2,2) space of (low,high)og -> (low,high)ibu(og) 
 
    # def compute_og_ibu_srm_graph(self, efficiency=None, include_style_range=False):
