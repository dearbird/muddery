
"""
This contains a simple view for rendering the webclient
page and serve it eventual static content.

"""
from __future__ import print_function

import tempfile, time, json, re, os
from django import http
from django.shortcuts import render
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.conf import settings
from django.core.exceptions import ValidationError
from evennia.server.sessionhandler import SESSIONS
from evennia.utils import logger
from muddery.utils import exporter
from muddery.utils import importer
from muddery.utils import readers
from muddery.utils import writers
from muddery.utils.builder import build_all
from muddery.utils.localized_strings_handler import LS, LOCALIZED_STRINGS_HANDLER
from muddery.utils.game_settings import CLIENT_SETTINGS
from muddery.worlddata.editor import page_view
from muddery.worlddata.editor.form_view import FormView
from muddery.worlddata.editor.single_form_view import SingleFormView
from muddery.worlddata.editor.relative_view import RelativeView
from muddery.worlddata.editor.dialogue_view import DialogueView
from muddery.worlddata.editor.dialogue_sentence_view import DialogueSentenceView
from muddery.worlddata.editor.dialogue_chain_view import DialogueChainView
from muddery.worlddata.editor.dialogue_chain_image import DialogueChainImage
from muddery.worlddata.data_sets import DATA_SETS


@staff_member_required
def worldeditor(request):
    """
    World Editor page template loading.
    """
    if "export_game_data" in request.GET:
        return export_game_data(request)
    elif "export_resources" in request.GET:
        return export_resources(request)
    elif "export_data_single" in request.GET:
        return export_data_single(request)
    elif "import_data_all" in request.FILES:
        return import_data_all(request)
    elif "import_resources_all" in request.FILES:
        return import_resources_all(request)
    elif "import_data_single" in request.FILES:
        return import_data_single(request)
    elif "apply" in request.POST:
        return apply_changes(request)

    return world_editor(request)


@staff_member_required
def world_editor(request):
    """
    Render the world editor.
    """
    data_handlers = DATA_SETS.all_handlers
    models = [{"key": data_handler.model_name, "name": LS(data_handler.model_name, category="models") + "(" + data_handler.model_name + ")"} for data_handler in data_handlers]

    context = {"models": models,
               "writers": writers.get_writers()}
    return render(request, 'worldeditor.html', context)


def file_iterator(file, erase=False, chunk_size=512):
    while True:
        c = file.read(chunk_size)
        if c:
            yield c
        else:
            # remove temp file
            file.close()
            if erase:
                os.remove(file.name)
            break


@staff_member_required
def export_game_data(request):
    """
    Export game world files.
    """
    response = http.HttpResponseNotModified()
    file_type = request.GET.get("file_type", None)

    # get data's zip
    zipfile = None
    try:
        zipfile = tempfile.TemporaryFile()
        exporter.export_zip_all(zipfile, file_type)
        zipfile.seek(0)

        filename = time.strftime("worlddata_%Y%m%d_%H%M%S.zip", time.localtime())
        response = http.StreamingHttpResponse(file_iterator(zipfile))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="%s"' % filename
    except Exception, e:
        message = "Can't export game data: %s" % e
        logger.log_tracemsg(message)

        zipfile.close()
        return render(request, 'fail.html', {"message": message})

    return response


@staff_member_required
def export_data_single(request):
    """
    Export a data table.
    """
    response = http.HttpResponseNotModified()
    model_name = request.GET.get("model_name", None)
    file_type = request.GET.get("file_type", None)

    if not file_type:
        # Default file type.
        file_type = "csv"

    writer_class = writers.get_writer(file_type)
    if not writer_class:
        return render(request, 'fail.html', {"message": "Can not export this type of file."})

    # Get tempfile's name.
    temp_name = tempfile.mktemp()
    temp_file = None
    try:
        exporter.export_file(temp_name, model_name, file_type)

        if writer_class.binary:
            open_mode = "rb"
        else:
            open_mode = "r"
        temp_file = open(temp_name, open_mode)

        filename = model_name + "." + writer_class.file_ext
        response = http.StreamingHttpResponse(file_iterator(temp_file, erase=True))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="%s"' % filename
    except Exception, e:
        message = "Can't export game data: %s" % e
        logger.log_tracemsg(message)

        if temp_file:
            temp_file.close()
            
        try:
            os.remove(temp_name)
        except Exception, e:
            pass

        return render(request, 'fail.html', {"message": message})

    return response


@staff_member_required
def export_resources(request):
    """
    Export resource files.
    """
    response = http.HttpResponseNotModified()

    # get data's zip
    zipfile = None
    try:
        zipfile = tempfile.TemporaryFile()
        exporter.export_resources(zipfile)
        zipfile.seek(0)

        filename = time.strftime("resources_%Y%m%d_%H%M%S.zip", time.localtime())
        response = http.StreamingHttpResponse(file_iterator(zipfile))
        response['Content-Type'] = 'application/octet-stream'
        response['Content-Disposition'] = 'attachment;filename="%s"' % filename
    except Exception, e:
        message = "Can't export resources: %s" % e
        logger.log_tracemsg(message)

        zipfile.close()
        return render(request, 'fail.html', {"message": message})

    return response


@staff_member_required
def import_data_all(request):
    """
    Import the game world from an uploaded zip file.
    """
    response = http.HttpResponseNotModified()
    file_obj = request.FILES.get("import_data_all", None)

    if file_obj:
        with tempfile.TemporaryFile() as zipfile:
            try:
                for chunk in file_obj.chunks():
                    zipfile.write(chunk)
                importer.unzip_data_all(zipfile)
            except ValidationError, e:
                err_message = ""
                if not hasattr(e, "error_dict"):
                    e.error_dict = {"": e.error_list}
                for key, values in e.error_dict.items():
                    if key:
                        err_message += key + ": "
                    for value in values:
                        err_message += value.message + "  "

                logger.log_tracemsg(err_message)
                return render(request, 'fail.html', {"message": str(e)})
            except Exception, e:
                logger.log_tracemsg("Cannot import game data: %s" % e)
                return render(request, 'fail.html', {"message": str(e)})

    return render(request, 'success.html', {"message": "World data imported!"})


@staff_member_required
def import_resources_all(request):
    """
    Import resources from an uploaded zip file.
    """
    response = http.HttpResponseNotModified()
    file_obj = request.FILES.get("import_resources_all", None)

    if file_obj:
        with tempfile.TemporaryFile() as zipfile:
            try:
                for chunk in file_obj.chunks():
                    zipfile.write(chunk)
                importer.unzip_resources_all(zipfile)
            except Exception, e:
                logger.log_tracemsg("Cannot import resources: %s" % e)
                return render(request, 'fail.html', {"message": str(e)})

    return render(request, 'success.html', {"message": "Resources imported!"})


@staff_member_required
def import_data_single(request):
    """
    Import the game world from an uploaded zip file.
    """
    response = http.HttpResponseNotModified()
    model_name = request.POST.get("model_name", None)
    upload_file = request.FILES.get("import_data_single", None)

    err_message = None
    if upload_file:
        # Get file type.
        (filename, ext_name) = os.path.splitext(upload_file.name)
        
        # If model name is empty, get model name from filename.
        if not model_name:
            model_name = filename

        # get data handler
        data_handler = DATA_SETS.get_handler(model_name)
        if not data_handler:
            logger.log_tracemsg("Cannot get data handler: %s" % model_name)
            return render(request, 'fail.html', {"message": "Can not import this file."})
            
        file_type = None
        if ext_name:
            file_type = ext_name[1:]

        reader_class = readers.get_reader(file_type)
        if not reader_class:
            return render(request, 'fail.html', {"message": "Can not import this type of file."})

        # Get tempfile's name.
        temp_name = tempfile.mktemp()

        if reader_class.binary:
            open_mode = "wb"
        else:
            open_mode = "w"
            
        with open(temp_name, open_mode) as temp_file:
            try:
                # Write to a template file.
                for chunk in upload_file.chunks():
                    temp_file.write(chunk)
                temp_file.flush()
                data_handler.import_file(temp_name, file_type=file_type)
            except ValidationError, e:
                err_message = ""
                if not hasattr(e, "error_dict"):
                    e.error_dict = {"": e.error_list}
                for key, values in e.error_dict.items():
                    if key:
                        err_message += key + ": "
                    for value in values:
                        err_message += value.message + "  "

                logger.log_tracemsg(err_message)
            except Exception, e:
                err_message = "Cannot import game data: %s" % e
                logger.log_tracemsg(err_message)

        try:
            os.remove(temp_name)
        except:
            pass
        
    if not err_message:
        return render(request, 'success.html', {"message": "World data imported!"})
    else:
        return render(request, 'fail.html', {"message": err_message})


@staff_member_required
def apply_changes(request):
    """
    Apply the game world's data.
    """
    try:
        # reload localized strings
        LOCALIZED_STRINGS_HANDLER.reload()

        # rebuild the world
        build_all()

        # send client settings
        CLIENT_SETTINGS.reset()
        client_settings = CLIENT_SETTINGS.all_values()
        client_settings["game_name"] = GAME_SETTINGS.get("game_name")
        text = json.dumps({"settings": client_settings})
        SESSIONS.announce_all(text)

        # restart the server
        SESSIONS.announce_all(" Server restarting ...")
        SESSIONS.server.shutdown(mode='reload')
    except Exception, e:
        message = "Can't build world: %s" % e
        logger.log_tracemsg(message)
        return render(request, 'fail.html', {"message": message})

    return render(request, 'success.html', {"message": LS("Data applied.")})


@staff_member_required
def editor(request):
    """
    World Editor page template loading.
    """
    try:
        name = re.sub(r"^/worlddata/editor/", "", request.path)
        return render(request, name, {"self": request.get_full_path()})
    except Exception, e:
        logger.log_tracemsg(e)
        raise http.Http404


@staff_member_required
def list_view(request):
    try:
        if "_back" in request.POST:
            return page_view.quit_list(request)
        else:
            return page_view.view_list(request)
    except Exception, e:
        logger.log_tracemsg("Invalid view request: %s" % e)

    raise http.Http404


@staff_member_required
def view_form(request):
    try:
        view = get_view(request)
        if view.is_valid():
            return view.view_form()
    except Exception, e:
        logger.log_tracemsg("Invalid view request: %s" % e)
        
    raise http.Http404


@staff_member_required
def submit_form(request):
    """
    Edit worlddata.

    Args:
        request:

    Returns:
        None.
    """
    try:
        view = get_view(request)

        if "_back" in request.POST:
            return view.quit_form()
        elif "_delete" in request.POST:
            if view.is_valid():
                return view.delete_form()
        else:
            if view.is_valid():
                return view.submit_form()
    except Exception, e:
        logger.log_tracemsg("Invalid edit request: %s" % e)
        
    raise http.Http404


@staff_member_required
def add_form(request):
    """
    Edit worlddata.

    Args:
        request:

    Returns:
        None.
    """
    try:
        view = get_view(request)
        if view.is_valid():
            return view.add_form()
    except Exception, e:
        logger.log_tracemsg("Invalid edit request: %s" % e)

    raise http.Http404


@staff_member_required
def get_view(request):
    """
    Get form view's object.

    Args:
        request: Http request.
    Returns:
        view
    """
    try:
        path_list = request.path.split("/")
        form_name = path_list[-2]
    except Exception, e:
        logger.log_errmsg("Invalid form.")
        raise http.Http404

    relative_forms = {
        "world_exits": {"CLASS_LOCKED_EXIT": "exit_locks",
                        "CLASS_TWO_WAY_EXIT": "two_way_exits"},
        "world_objects": {"CLASS_OBJECT_CREATOR": "object_creators"}
    }

    if form_name in relative_forms:
        view = RelativeView(form_name, request, relative_forms[form_name])
    elif form_name == "game_settings" or form_name == "client_settings":
        view = SingleFormView(form_name, request)
    elif form_name == "dialogues":
        view = DialogueView(form_name, request)
    elif form_name == "dialogue_sentences":
        view = DialogueSentenceView(form_name, request)
    elif form_name == "dialogue_relations":
        view = DialogueChainView(form_name, request)
    else:
        view = FormView(form_name, request)

    return view


@staff_member_required
def get_image(request):
    """
    Create an image.

    Args:
        request:

    Returns:

    """
    try:
        image_view = get_image_view(request)
        if image_view.is_valid():
            return image_view.render()
    except Exception, e:
        logger.log_tracemsg("Invalid image request: %s" % e)

    raise http.Http404


@staff_member_required
def get_image_view(request):
    """
    Get image's render.

    Args:
        request: Http request.
    Returns:
        view
    """
    try:
        path_list = request.path.split("/")
        form_name = path_list[-2]
    except Exception, e:
        logger.log_errmsg("Invalid form.")
        raise http.Http404

    if form_name == "dialogue_relations":
        return DialogueChainImage(form_name, request)

    raise http.Http404
