from django.urls import path

from . import views

urlpatterns = [
    path("", views.overblik, name="overblik"),
    path("debitorer/", views.debitorer, name="debitorer_start"),
    path("debitorer/<slug:kode>/", views.debitorer, name="debitorer"),
    path("debitorer/<slug:kode>/hent/", views.debitor_hent, name="debitor_hent"),
    path("debitorer/<slug:kode>/forventet/", views.forventet_opret, name="forventet_opret"),
    path("debitorer/forventet/<int:pk>/fjern/", views.forventet_fjern, name="forventet_fjern"),
    path("debitorer/faktura/<int:faktura_id>/vurdering/", views.debitor_vurdering, name="debitor_vurdering"),
    path("kreditorer/", views.kreditorer, name="kreditorer_start"),
    path("kreditorer/<slug:kode>/", views.kreditorer, name="kreditorer"),
    path("kreditorer/<slug:kode>/hent/", views.kreditor_hent, name="kreditor_hent"),
    path("kreditorer/post/<int:post_id>/vurdering/", views.kreditor_vurdering, name="kreditor_vurdering"),
    path("forecast/", views.forecast_vis, name="forecast"),
    path("forecast/<int:aar>/q<int:kvartal>/", views.forecast_vis, name="forecast_kvartal"),
    path("forecast/<int:aar>/q<int:kvartal>/gem/", views.forecast_gem_version, name="forecast_gem_version"),
    path("forecast/post/", views.forecast_post, name="forecast_post"),
    path("versioner/", views.versioner, name="versioner"),
    path("versioner/<int:pk>/", views.version_vis, name="version"),
    path("pleo/", views.pleo, name="pleo"),
    path("pleo/<int:aar>/q<int:kvartal>/", views.pleo, name="pleo_kvartal"),
    path("pleo/budget/", views.pleo_budget, name="pleo_budget"),
    path("pleo/<slug:kode>/afdeling/", views.pleo_afdeling, name="pleo_afdeling"),
    path("opsaetning/", views.opsaetning, name="opsaetning"),
]
