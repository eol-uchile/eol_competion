# -*- coding: utf-8 -*-

from __future__ import unicode_literals

import six
import json

from datetime import datetime
from courseware.courses import get_course_with_access
from django.template.loader import render_to_string
from django.shortcuts import render_to_response
from web_fragments.fragment import Fragment
from django.core.cache import cache
from openedx.core.djangoapps.plugin_api.views import EdxFragmentView
from lms.djangoapps.certificates.models import GeneratedCertificate
from xblock.fields import Scope
from opaque_keys.edx.keys import CourseKey, UsageKey
from opaque_keys import InvalidKeyError
from django.contrib.auth.models import User

from xblock_discussion import DiscussionXBlock
from xmodule.modulestore.django import modulestore
from xmodule.modulestore.inheritance import compute_inherited_metadata, own_metadata

from completion.models import BlockCompletion
from collections import OrderedDict
# Create your views here.

FILTER_LIST = ['xml_attributes']
INHERITED_FILTER_LIST = ['children', 'xml_attributes']


class EolCompletionFragmentView(EdxFragmentView):
    def render_to_fragment(self, request, course_id, **kwargs):

        context = self.get_context(request, course_id)
        html = render_to_string(
            'eol_completion/eol_completion_fragment.html', context)
        fragment = Fragment(html)
        return fragment

    def get_context(self, request, course_id):
        course_key = CourseKey.from_string(course_id)
        course = get_course_with_access(request.user, "load", course_key)

        data = cache.get("eol_completion-" + course_id + "-data")
        if data is None:
            enrolled_students = User.objects.filter(
                courseenrollment__course_id=course_key,
                courseenrollment__is_active=1
            ).order_by('username').values('id', 'username', 'email')
            store = modulestore()
            # Dictionary with all course blocks
            info = self.dump_module(store.get_course(course_key))
            course_aux = course_id.split(":", 1)
            id_course = 'block-v1:' + \
                course_aux[1] + '+type@course+block@course'

            data = []
            content, max_unit = self.get_content(info, id_course)
            user_tick = self.get_ticks(
                content, info, enrolled_students, course_key, max_unit)
            time = datetime.now()
            time = time.strftime("%d/%m/%Y, %H:%M:%S")
            data.extend([user_tick, content, max_unit, time])
            cache.set("eol_completion-" + course_id + "-data", data, 300)

        context = {
            "course": course,
            "lista_tick": data[0],
            "content": data[1],
            "max": data[2],
            "time": data[3]
        }

        return context

    def get_content(self, info, id_course):
        """
            Returns dictionary of ordered sections, subsections and units
        """
        max_unit = 0   # Number of units in all sections
        content = OrderedDict()
        children_course = info[id_course]
        children_course = children_course['children']  # All course sections
        children = 0  # Number of units per section
        for id_section in children_course:  # Iterate each section
            section = info[id_section]
            aux_name_sec = section['metadata']
            children = 0
            content[id_section] = {
                'type': 'section',
                'name': aux_name_sec['display_name'],
                'id': id_section,
                'num_children': children}
            subsections = section['children']
            for id_subsection in subsections:  # Iterate each subsection
                subsection = info[id_subsection]
                units = subsection['children']
                aux_name = subsection['metadata']
                children += len(units)
                content[id_subsection] = {
                    'type': 'subsection',
                    'name': aux_name['display_name'],
                    'id': id_subsection,
                    'num_children': len(units)}
                for id_uni in units:  # Iterate each unit and get unit name
                    max_unit += 1
                    unit = info[id_uni]
                    content[id_uni] = {
                        'type': 'unit',
                        'name': unit['metadata']['display_name'],
                        'id': id_uni}
            content[id_section] = {
                'type': 'section',
                'name': aux_name_sec['display_name'],
                'id': id_section,
                'num_children': children}

        return content, max_unit

    def get_ticks(
            self,
            content,
            info,
            enrolled_students,
            course_key,
            max_unit):
        """
            Dictionary of students with true/false if students completed the units
        """
        user_tick = OrderedDict()

        for user in enrolled_students:  # Iterate each student
            certificate = self.get_certificate(user['id'], course_key)

            blocks = BlockCompletion.objects.filter(
                user=user['id'], course_key=course_key)
            # Get a list of true/false if they completed the units
            # and number of completed units
            data = self.get_data_tick(content, info, user, blocks, max_unit)

            user_tick[user['id']] = {'user': user['id'],
                                     'username': user['username'],
                                     'email': user['email'],
                                     'certificate': certificate,
                                     'data': data}
        return user_tick

    def get_data_tick(self, content, info, user, blocks, max_unit):
        """
            Get a list of true/false if they completed the units
            and number of completed units
        """
        data = []
        completed_unit = 0  # Number of completed units per student
        completed_unit_per_section = 0  # Number of completed units per section
        num_units_section = 0  # Number of units per section
        first = True
        for unit in content.items():
            if unit[1]['type'] == 'unit':
                unit_info = info[unit[1]['id']]
                # Unit Block
                blocks_unit = unit_info['children']
                checker = self.get_block_tick(blocks_unit, blocks)
                completed_unit_per_section += 1
                num_units_section += 1
                completed_unit += 1
                data.append(checker)
                if not checker:
                    completed_unit -= 1
                    completed_unit_per_section -= 1

            if not first and unit[1]['type'] == 'section' and unit[1]['num_children'] > 0:
                aux_point = str(completed_unit_per_section) + \
                    "/" + str(num_units_section)
                data.append(aux_point)
                completed_unit_per_section = 0
                num_units_section = 0
            if first and unit[1]['type'] == 'section' and unit[1]['num_children'] > 0:
                first = False
        aux_point = str(completed_unit_per_section) + \
            "/" + str(num_units_section)
        data.append(aux_point)
        aux_final_point = str(completed_unit) + "/" + str(max_unit)
        data.append(aux_final_point)
        return data

    def get_block_tick(sefl, blocks_unit, blocks):
        """
            Check if unit block is completed
        """
        checker = True
        i = 0
        while checker and i < len(blocks_unit):
            # Iterate each block
            block = blocks_unit[i]
            dicussion_block = block.split('@')
            if dicussion_block[1] != 'discussion+block':
                usage_key = UsageKey.from_string(block)
                aux_block = blocks.filter(
                    block_key=usage_key).values('completion')

                if aux_block.count() == 0 or aux_block[0] == 0.0:
                    # If block hasnt been seen or completed
                    checker = False
            i += 1
        return checker

    def get_certificate(self, user_id, course_id):
        """
            Check if user has generated a certificate
        """
        certificate = GeneratedCertificate.certificate_for_student(
            user_id, course_id)
        if certificate is None:
            return 'No'
        return 'Si'

    def dump_module(
            self,
            module,
            destination=None,
            inherited=False,
            defaults=False):
        """
        Add the module and all its children to the destination dictionary in
        as a flat structure.
        """

        destination = destination if destination else {}

        items = own_metadata(module)

        # HACK: add discussion ids to list of items to export (AN-6696)
        if isinstance(
                module,
                DiscussionXBlock) and 'discussion_id' not in items:
            items['discussion_id'] = module.discussion_id

        filtered_metadata = {
            k: v for k,
            v in six.iteritems(items) if k not in FILTER_LIST}

        destination[six.text_type(module.location)] = {
            'category': module.location.block_type,
            'children': [six.text_type(child) for child in getattr(module, 'children', [])],
            'metadata': filtered_metadata,
        }

        if inherited:
            # When calculating inherited metadata, don't include existing
            # locally-defined metadata
            inherited_metadata_filter_list = list(filtered_metadata.keys())
            inherited_metadata_filter_list.extend(INHERITED_FILTER_LIST)

            def is_inherited(field):
                if field.name in inherited_metadata_filter_list:
                    return False
                elif field.scope != Scope.settings:
                    return False
                elif defaults:
                    return True
                else:
                    return field.values != field.default

            inherited_metadata = {field.name: field.read_json(
                module) for field in module.fields.values() if is_inherited(field)}
            destination[six.text_type(
                module.location)]['inherited_metadata'] = inherited_metadata

        for child in module.get_children():
            self.dump_module(child, destination, inherited, defaults)

        return destination
