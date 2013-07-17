# coding: utf-8
# Copyright 2013 The Font Bakery Authors. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
#
# See AUTHORS.txt for the list of Authors and LICENSE.txt for the License.
#pylint:disable-msg=E1101

import logging

from flask import (Blueprint, render_template, g, flash, request,
    url_for, redirect)
from flask.ext.babel import gettext as _

from ..decorators import login_required
# from ..extensions import db
from ..tasks import (read_tree, read_license, read_metadata, save_metadata, read_description,
    save_description, read_log, read_yaml, project_tests, sync_and_process)
from .models import Project

project = Blueprint('project', __name__, static_folder='../../data/', url_prefix='/project')

DEFAULT_SUBSET_LIST = ['menu', 'latin', 'latin-ext+latin', 'cyrillic+latin', 'cyrillic-ext+latin',
    'greek+latin', 'greek-ext+latin', 'vietnamese+latin']

@project.before_request
def before_request():
    if g.user:
        g.projects = Project.query.filter_by(login=g.user.login).all()

@project.route('/bump', methods=['GET'])
@login_required
def bump():
    project_id = request.args.get('project_id')
    #pylint:disable-msg=E1101
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    logging.info('Update for project %s by %s' % (project_id, g.user.login))
    sync_and_process(p)
    flash(_("Git %s was updated" % p.clone))
    return redirect(url_for('project.fonts', project_id = project_id))

@project.route('/<int:project_id>/setup', methods=['GET', 'POST'])
@login_required
def setup(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    state = p.state

    #import ipdb; ipdb.set_trace()
    if request.method == 'GET':
        return render_template('project/setup.html', project = p, state = state,
            subsetvals = DEFAULT_SUBSET_LIST)
    else:
        if request.form.get('step') == '2':
            # 1st step
            if request.form.get('license_file') in state['txt_files']:
                state['license_file'] = request.form.get('license_file')
            else:
                flash(_("Wrong license_file value, must be an error"))
                return render_template('project/setup.html', project = p, state = state,
                    subsetvals = DEFAULT_SUBSET_LIST)

            if request.form.get('rename') == 'yes':
                state['rename'] = True
            else:
                state['rename'] = False

            ufo_dirs = request.form.getlist('ufo_dirs')
            for i in ufo_dirs:
                if i not in state['ufo_dirs']:
                    flash(_("Wrong ufo_dir value, must be an error"))
                    return render_template('project/setup.html', project = p, state = state,
                        subsetvals = DEFAULT_SUBSET_LIST)
                if not state['out_ufo'].get(i):
                    # define font name based on ufo folder name.
                    state['out_ufo'][i] = i.split('/')[-1][:-4]
                else:
                    if state['rename'] == False:
                        state['out_ufo'][i] = i.split('/')[-1][:-4]
            for i in state['out_ufo'].keys():
                # don't want to delete other properties
                if i not in ufo_dirs:
                    del state['out_ufo'][i]

            subset_list = request.form.getlist('subset')
            for i in subset_list:
                try:
                    assert i in DEFAULT_SUBSET_LIST
                except AssertionError:
                    flash('Subset value is wrong')
                    return render_template('project/setup.html', project = p, state = state,
                        subsetvals = DEFAULT_SUBSET_LIST)

            state['subset'] = subset_list

            if request.form.get('ttfautohintuse'):
                state['ttfautohintuse'] = True
            else:
                state['ttfautohintuse'] = False

            if request.form.get('ttfautohint'):
                state['ttfautohint'] = request.form.get('ttfautohint')

            # setup is done, now you can process files
            state['autoprocess'] = True

            p.save_state()

            if request.form.get('rename') == 'yes':
                return render_template('project/setup2.html', project = p, state = state)
            else:
                flash(_("Repository %s has been updated" % p.clone))
                sync_and_process.delay(p)
                return redirect(url_for('project.fonts', project_id=p.id))
        elif request.form.get('step')=='3':
            out_ufo = {}
            for param, value in request.form.items():
                if not param.startswith('ufo-'):
                    continue
                if param[4:] in state['out_ufo']:
                    # XXX: there is no sanity check for value yet
                    out_ufo[param[4:]] = value
                else:
                    flash(_("Wrong parameter provided for ufo folder name"))
            state['out_ufo'] = out_ufo
            p.save_state()

            # push check before project process
            sync_and_process.delay(p)
            return redirect(url_for('project.fonts', project_id=p.id))
        else:
            flash(_("Strange behaviour detected"))
            return redirect(url_for('project.fonts', project_id=p.id))

@project.route('/<int:project_id>/', methods=['GET'])
@login_required
def fonts(project_id):
    # this page can be visible by others, not only by owner
    p = Project.query.get_or_404(project_id)
    if p.state.get('autoprocess'):
        tree = read_tree(login = g.user.login, project_id = p.id)
        return render_template('project/fonts.html', project = p, tree = tree)
    else:
        return redirect(url_for('project.setup', project_id = p.id))

@project.route('/<int:project_id>/license', methods=['GET'])
@login_required
def plicense(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    lic = read_license(login = g.user.login, project_id = p.id)
    return render_template('project/license.html', project = p, license = lic)

@project.route('/<int:project_id>/ace', methods=['GET'])
@login_required
def ace(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    metadata, metadata_new = read_metadata(login = g.user.login, project_id = p.id)
    return render_template('project/ace.html', project = p,
        metadata = metadata, metadata_new = metadata_new)

@project.route('/<int:project_id>/ace', methods=['POST'])
@login_required
def ace_save(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    save_metadata(login = g.user.login, project_id = p.id,
        metadata = request.form.get('metadata'),
        del_new = request.form.get('delete', None))
    flash('METADATA.json saved')
    return redirect(url_for('project.ace', project_id=p.id))


@project.route('/<int:project_id>/description_edit', methods=['GET'])
@login_required
def description_edit(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    description = read_description(login = g.user.login, project_id = p.id)
    return render_template('project/description.html', project = p,
        description = description)

@project.route('/<int:project_id>/description_save', methods=['POST'])
@login_required
def description_save(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    save_description(login = g.user.login, project_id = p.id,
        description = request.form.get('description'))
    flash('Description saved')
    return redirect(url_for('project.description_edit', project_id=p.id))

@project.route('/<int:project_id>/log', methods=['GET'])
@login_required
def buildlog(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    log = read_log(login = g.user.login, project_id = p.id)
    return render_template('project/log.html', project = p,
        log = log)

@project.route('/<int:project_id>/yaml', methods=['GET'])
@login_required
def bakeryyaml(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    yaml = read_yaml(login = g.user.login, project_id = p.id)
    return render_template('project/yaml.html', project = p,
        yaml = yaml)

@project.route('/<int:project_id>/tests', methods=['GET'])
@login_required
def tests(project_id):
    p = Project.query.filter_by(login = g.user.login, id = project_id).first_or_404()
    test_result = project_tests(login = g.user.login, project_id = p.id)
    return render_template('project/tests.html', project = p,
        tests = test_result)

