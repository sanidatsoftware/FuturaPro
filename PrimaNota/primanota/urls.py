from django.urls import path

from . import views

urlpatterns = [
    path("", views.home, name="primanota_home"),
    path("upload/", views.upload, name="primanota_upload"),
    path("admin/", views.admin, name="primanota_admin"),
    path("monitor/", views.monitor, name="primanota_monitor"),
    path("giornata/<int:negozio_id>/<str:giorno>/", views.giornata, name="primanota_giornata"),
    path("update-lavorato/<int:scansione_id>/", views.update_lavorato, name="primanota_update_lavorato"),
    path("delete/<int:scansione_id>/", views.delete, name="primanota_delete"),
    path("note/", views.note, name="primanota_note"),
    path("note/<int:nota_id>/chiudi/", views.chiudi_nota, name="primanota_chiudi_nota"),
    path("sysspy/", views.sysspy_archivio, name="primanota_sysspy"),
    path("sysspy/<int:file_id>/", views.sysspy_dettaglio, name="primanota_sysspy_dettaglio"),
    path("sysspy/<int:file_id>/scarica/", views.sysspy_scarica, name="primanota_sysspy_scarica"),
    path("condivisioni/", views.condivisioni, name="primanota_condivisioni"),
    path("condivisioni/<int:negozio_id>/importa/", views.avvia_importazione, name="primanota_importa"),
    path("importazione/<str:lavoro>/", views.stato_importazione, name="primanota_importazione"),
]
