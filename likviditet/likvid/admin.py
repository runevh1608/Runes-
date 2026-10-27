from django.contrib import admin

from .models import (Aendringslog, Bankkonto, DebitorFaktura, DebitorVurdering, ForecastLinje, ForecastSnapshot,
                     ForventetFaktura, PleoAfdeling, PleoBudget, Selskab)


class LinjeInline(admin.TabularInline):
    model = ForecastLinje
    extra = 0
    fields = ("raekkefoelge", "kode", "navn", "type", "kilde", "sum_af")


@admin.register(Selskab)
class SelskabAdmin(admin.ModelAdmin):
    list_display = ("navn", "standard_kredit_dage", "minimumssaldo")
    inlines = [LinjeInline]


@admin.register(Bankkonto)
class BankkontoAdmin(admin.ModelAdmin):
    list_display = ("selskab", "navn", "kontonummer", "primo_saldo", "primo_dato")


class VurderingInline(admin.TabularInline):
    model = DebitorVurdering
    extra = 0
    readonly_fields = ("forventet_dato", "kommentar", "oprettet", "oprettet_af")
    can_delete = False

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(DebitorFaktura)
class DebitorFakturaAdmin(admin.ModelAdmin):
    list_display = ("selskab", "nummer", "kunde_navn", "fakturadato", "restbeloeb_dkk", "aaben", "lukket_dato")
    list_filter = ("selskab", "aaben")
    search_fields = ("nummer", "kunde_navn")
    inlines = [VurderingInline]

    def has_change_permission(self, request, obj=None):
        return False  # Spejl af e-conomic

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ForventetFaktura)
class ForventetFakturaAdmin(admin.ModelAdmin):
    list_display = ("selskab", "beskrivelse", "beloeb", "fra_dato", "til_dato", "kredit_dage", "aktiv")
    list_filter = ("selskab", "aktiv")


class BudgetInline(admin.TabularInline):
    model = PleoBudget
    extra = 0


@admin.register(PleoAfdeling)
class PleoAfdelingAdmin(admin.ModelAdmin):
    list_display = ("selskab", "navn", "aktiv")
    inlines = [BudgetInline]


@admin.register(ForecastSnapshot)
class ForecastSnapshotAdmin(admin.ModelAdmin):
    list_display = ("oprettet", "titel", "aarsag", "oprettet_af")
    readonly_fields = [f.name for f in ForecastSnapshot._meta.fields]

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Aendringslog)
class AendringslogAdmin(admin.ModelAdmin):
    list_display = ("tidspunkt", "bruger", "objekt", "gammel", "ny")
    readonly_fields = ("tidspunkt", "bruger", "objekt", "gammel", "ny")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
