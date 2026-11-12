"""Declarative content for the local seed dataset.

Only data lives here. Add or adjust entries freely; the runner in `local.py`
translates these specs into application use case calls.

Relationships are expressed by name so that specs stay readable: a task points at
its parent domain, process, or project by name, a contact points at task titles,
and a journal entry points at project titles, task titles, and contact names.
Names that do not resolve are skipped rather than failing the run.
"""

from dataclasses import dataclass

from sidekick.journal.domain.entry import KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.tasks.domain import Priority


@dataclass(frozen=True, slots=True)
class DomainSpec:
    name: str
    description: str


@dataclass(frozen=True, slots=True)
class ProcessSpec:
    name: str
    domain: str
    description: str


@dataclass(frozen=True, slots=True)
class ProjectSpec:
    title: str
    domain: str
    description: str
    start_offset_days: int
    target_offset_days: int


@dataclass(frozen=True, slots=True)
class ActionSpec:
    title: str
    due_offset_days: int | None = None


@dataclass(frozen=True, slots=True)
class StepSpec:
    title: str
    due_offset_days: int | None = None
    actions: tuple[ActionSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class TaskSpec:
    title: str
    parent_kind: str  # "domain" | "process" | "project"
    parent_name: str
    description: str
    priority: Priority
    due_offset_days: int | None = None
    steps: tuple[StepSpec, ...] = ()


@dataclass(frozen=True, slots=True)
class ContactSpec:
    display_name: str
    context_note: str
    email: str | None = None
    phone: str | None = None
    aliases: tuple[str, ...] = ()
    task_titles: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class JournalSpec:
    day_offset: int
    hour: int
    title: str
    summary: str
    raw_text: str
    key_points: tuple[tuple[KeyPointKind, str], ...]
    source_type: SourceType = SourceType.MANUAL_TEXT
    project_titles: tuple[str, ...] = ()
    task_titles: tuple[str, ...] = ()
    contact_names: tuple[str, ...] = ()


DOMAINS: tuple[DomainSpec, ...] = (
    DomainSpec("Arbete", "Yrkesroll, uppdrag, kunder och allt som hör till jobbet."),
    DomainSpec("Hem och familj", "Hushåll, ekonomi, hälsa och familjelogistik."),
)

PROCESSES: tuple[ProcessSpec, ...] = (
    ProcessSpec(
        "Veckoplanering",
        "Arbete",
        "Återkommande genomgång av veckan: planera, rensa inkorgen och sätta fokus.",
    ),
    ProcessSpec(
        "Kundsupport",
        "Arbete",
        "Löpande hantering av inkommande kundärenden utan definierat slutdatum.",
    ),
    ProcessSpec(
        "Hushållsrutiner",
        "Hem och familj",
        "Städning, tvätt, matplanering och andra rutiner som aldrig blir klara.",
    ),
)

PROJECTS: tuple[ProjectSpec, ...] = (
    ProjectSpec(
        "Sidekick MVP",
        "Arbete",
        "Leverera en körbar första version av Sidekick med projekt, uppgifter och journal.",
        start_offset_days=-21,
        target_offset_days=30,
    ),
    ProjectSpec(
        "Kontorsflytt",
        "Arbete",
        "Flytta teamet till nya lokaler inklusive nät, möbler och avtal.",
        start_offset_days=-7,
        target_offset_days=45,
    ),
    ProjectSpec(
        "Renovera köket",
        "Hem och familj",
        "Byta bänkskiva, måla skåpluckor och installera ny diskmaskin.",
        start_offset_days=-3,
        target_offset_days=60,
    ),
)

TASKS: tuple[TaskSpec, ...] = (
    TaskSpec(
        title="Skriv releasenoteringar för MVP",
        parent_kind="project",
        parent_name="Sidekick MVP",
        description="Sammanfatta vad som faktiskt ingår i första körbara versionen.",
        priority=Priority.HIGH,
        due_offset_days=3,
        steps=(
            StepSpec(
                "Samla ändringar från git-loggen",
                due_offset_days=1,
                actions=(
                    ActionSpec("Lista commits sedan förra taggen"),
                    ActionSpec("Gruppera per funktionsområde"),
                ),
            ),
            StepSpec(
                "Skriv utkast på svenska",
                due_offset_days=2,
                actions=(
                    ActionSpec("Formulera rubriker"),
                    ActionSpec("Beskriv kända begränsningar", due_offset_days=2),
                ),
            ),
            StepSpec("Läs igenom och putsa språket", due_offset_days=3),
        ),
    ),
    TaskSpec(
        title="Verifiera MCP-verktygens kontrakt",
        parent_kind="project",
        parent_name="Sidekick MVP",
        description="Kör exportkommandona och jämför mot sparade kontraktsfiler.",
        priority=Priority.URGENT,
        due_offset_days=-1,
        steps=(
            StepSpec(
                "Exportera OpenAPI och MCP-kontrakt",
                actions=(
                    ActionSpec("Kör sidekick-openapi"),
                    ActionSpec("Kör mcp.export_contract"),
                ),
            ),
            StepSpec(
                "Granska diffen",
                due_offset_days=-1,
                actions=(
                    ActionSpec(
                        "Bekräfta att inga oavsiktliga brytande ändringar finns"
                    ),
                ),
            ),
        ),
    ),
    TaskSpec(
        title="Boka nätverksleverantör",
        parent_kind="project",
        parent_name="Kontorsflytt",
        description="Fiber och wifi måste vara på plats innan inflyttning.",
        priority=Priority.HIGH,
        due_offset_days=10,
        steps=(
            StepSpec(
                "Ta in tre offerter",
                due_offset_days=5,
                actions=(
                    ActionSpec("Kontakta leverantör A"),
                    ActionSpec("Kontakta leverantör B"),
                    ActionSpec("Kontakta leverantör C"),
                ),
            ),
            StepSpec("Jämför pris och leveranstid", due_offset_days=7),
            StepSpec(
                "Signera avtal",
                due_offset_days=10,
                actions=(ActionSpec("Kontrollera uppsägningstid"),),
            ),
        ),
    ),
    TaskSpec(
        title="Inventera möbler som ska med",
        parent_kind="project",
        parent_name="Kontorsflytt",
        description="Allt gammalt ska inte följa med till nya lokalen.",
        priority=Priority.NORMAL,
        due_offset_days=14,
        steps=(
            StepSpec(
                "Gå igenom rum för rum",
                actions=(
                    ActionSpec("Märk upp det som slängs"),
                    ActionSpec("Fotografera det som säljs"),
                ),
            ),
        ),
    ),
    TaskSpec(
        title="Beställ ny bänkskiva",
        parent_kind="project",
        parent_name="Renovera köket",
        description="Mått är tagna, men materialval är inte bestämt.",
        priority=Priority.NORMAL,
        due_offset_days=7,
        steps=(
            StepSpec(
                "Välj material",
                due_offset_days=4,
                actions=(
                    ActionSpec("Hämta prover"),
                    ActionSpec("Kontrollera pris per meter"),
                ),
            ),
            StepSpec("Lägg beställning", due_offset_days=7),
        ),
    ),
    TaskSpec(
        title="Planera kommande vecka",
        parent_kind="process",
        parent_name="Veckoplanering",
        description="Återkommande genomgång som hör till processen, inte ett projekt.",
        priority=Priority.NORMAL,
        due_offset_days=2,
        steps=(
            StepSpec(
                "Töm inkorgen",
                due_offset_days=2,
                actions=(
                    ActionSpec("Svara på det som tar under två minuter"),
                    ActionSpec("Lyft resten till uppgifter"),
                ),
            ),
            StepSpec("Välj tre fokusområden", due_offset_days=2),
        ),
    ),
    TaskSpec(
        title="Rensa gamla supportärenden",
        parent_kind="process",
        parent_name="Kundsupport",
        description="Ärenden utan svar på 30 dagar ska stängas med ett vänligt meddelande.",
        priority=Priority.LOW,
        due_offset_days=21,
        steps=(
            StepSpec(
                "Lista inaktiva ärenden",
                actions=(ActionSpec("Filtrera på senaste svar"),),
            ),
            StepSpec("Skicka avslutsmeddelanden", due_offset_days=21),
        ),
    ),
    TaskSpec(
        title="Se över svarstidsmål",
        parent_kind="process",
        parent_name="Kundsupport",
        description="Nuvarande mål känns satt på magkänsla snarare än data.",
        priority=Priority.NORMAL,
        steps=(
            StepSpec(
                "Ta fram statistik för kvartalet",
                actions=(
                    ActionSpec("Exportera ärendedata"),
                    ActionSpec("Räkna median och p90"),
                ),
            ),
        ),
    ),
    TaskSpec(
        title="Storhandla inför helgen",
        parent_kind="process",
        parent_name="Hushållsrutiner",
        description="Matplanering först, inköpslista sedan.",
        priority=Priority.NORMAL,
        due_offset_days=4,
        steps=(
            StepSpec(
                "Planera veckans måltider",
                due_offset_days=3,
                actions=(ActionSpec("Kolla vad som finns i frysen"),),
            ),
            StepSpec("Skriv inköpslista", due_offset_days=4),
        ),
    ),
    TaskSpec(
        title="Boka tandläkartid",
        parent_kind="domain",
        parent_name="Hem och familj",
        description="Hör direkt till domänen utan att passa i en process eller ett projekt.",
        priority=Priority.LOW,
        due_offset_days=25,
        steps=(
            StepSpec(
                "Ring mottagningen", actions=(ActionSpec("Fråga efter kvällstid"),)
            ),
        ),
    ),
    TaskSpec(
        title="Uppdatera CV och profil",
        parent_kind="domain",
        parent_name="Arbete",
        description="Ligger på domännivå eftersom det inte tillhör ett enskilt uppdrag.",
        priority=Priority.LOW,
        steps=(
            StepSpec(
                "Lägg in senaste uppdraget",
                actions=(ActionSpec("Skriv två meningar om resultatet"),),
            ),
            StepSpec("Uppdatera profilbild"),
        ),
    ),
    TaskSpec(
        title="Följ upp fakturor",
        parent_kind="domain",
        parent_name="Arbete",
        description="Två fakturor är förfallna och behöver en påminnelse.",
        priority=Priority.HIGH,
        due_offset_days=-3,
        steps=(
            StepSpec(
                "Sammanställ obetalda fakturor",
                due_offset_days=-3,
                actions=(
                    ActionSpec("Kontrollera betalningsstatus"),
                    ActionSpec("Skicka påminnelse"),
                ),
            ),
        ),
    ),
)

CONTACTS: tuple[ContactSpec, ...] = (
    ContactSpec(
        display_name="Anna Lindqvist",
        context_note="Produktägare för Sidekick. Vill ha korta statusuppdateringar på fredagar.",
        email="anna.lindqvist@example.com",
        phone="+46701740605",
        aliases=("Anna L",),
        task_titles=(
            "Skriv releasenoteringar för MVP",
            "Verifiera MCP-verktygens kontrakt",
        ),
    ),
    ContactSpec(
        display_name="Björn Ek",
        context_note="Kontaktperson hos fastighetsägaren inför kontorsflytten.",
        email="bjorn.ek@example.com",
        phone="+46701740606",
        task_titles=("Boka nätverksleverantör", "Inventera möbler som ska med"),
    ),
    ContactSpec(
        display_name="Carina Öberg",
        context_note="Snickare som tar bänkskivan och skåpluckorna i köket.",
        phone="+46701740607",
        aliases=("Carina snickaren",),
        task_titles=("Beställ ny bänkskiva",),
    ),
    ContactSpec(
        display_name="David Nyström",
        context_note="Kollega i supportteamet, äger svarstidsmålen tillsammans med mig.",
        email="david.nystrom@example.com",
        task_titles=("Se över svarstidsmål", "Rensa gamla supportärenden"),
    ),
    ContactSpec(
        display_name="Eva Sandberg",
        context_note="Revisor. Hör av sig när fakturor ligger kvar för länge.",
        email="eva.sandberg@example.com",
        phone="+46701740608",
        aliases=("Eva S", "Revisorn"),
        task_titles=("Följ upp fakturor",),
    ),
)

JOURNAL_ENTRIES: tuple[JournalSpec, ...] = (
    JournalSpec(
        day_offset=-2,
        hour=17,
        title="Avstämning om MVP-innehåll",
        summary="Anna och jag landade i vad som faktiskt ingår i första versionen.",
        raw_text=(
            "Satt med Anna i en timme och gick igenom MVP-omfattningen. Vi enades om att "
            "journalen ingår men att AI-genereringen förblir avstängd lokalt. Jag lovade "
            "releasenoteringar innan fredag. Kände mig lugnare efteråt än på flera veckor."
        ),
        key_points=(
            (KeyPointKind.DECISION, "Journal-AI förblir avstängd i första versionen."),
            (KeyPointKind.COMMITMENT, "Releasenoteringar klara innan fredag."),
            (KeyPointKind.REFLECTION, "Tydlig omfattning gör att stressen släpper."),
        ),
        project_titles=("Sidekick MVP",),
        task_titles=("Skriv releasenoteringar för MVP",),
        contact_names=("Anna Lindqvist",),
    ),
    JournalSpec(
        day_offset=-1,
        hour=9,
        title="Visning av nya lokalen",
        summary="Lokalen fungerar, men nätverket är den stora frågan.",
        raw_text=(
            "Björn visade lokalen på morgonen. Ytan räcker och ljuset är bra, men det finns "
            "ingen fiber indragen. Han tror att det tar fyra veckor. Om det stämmer måste "
            "leverantören bokas den här veckan, annars sitter vi utan nät vid inflyttning."
        ),
        key_points=(
            (KeyPointKind.FACT, "Ingen fiber är indragen i den nya lokalen."),
            (
                KeyPointKind.QUESTION,
                "Håller fyra veckors ledtid för fiberinstallation?",
            ),
            (KeyPointKind.COMMITMENT, "Boka nätverksleverantör den här veckan."),
        ),
        project_titles=("Kontorsflytt",),
        task_titles=("Boka nätverksleverantör",),
        contact_names=("Björn Ek",),
    ),
    JournalSpec(
        day_offset=0,
        hour=20,
        title="Kvällsanteckning om köket och fakturorna",
        summary="Carina kan börja om två veckor. Fakturapåminnelser är fortfarande oskickade.",
        raw_text=(
            "Carina ringde och kan börja i köket om två veckor om bänkskivan är beställd. "
            "Jag hann inte skicka fakturapåminnelserna igen idag, tredje dagen i rad. "
            "Eva kommer att fråga om dem på måndag, så det får bli första punkten imorgon."
        ),
        key_points=(
            (KeyPointKind.FACT, "Carina kan starta köksarbetet om två veckor."),
            (
                KeyPointKind.REFLECTION,
                "Fakturapåminnelser skjuts upp trots att de tar minuter.",
            ),
            (KeyPointKind.COMMITMENT, "Skicka fakturapåminnelser först imorgon."),
        ),
        project_titles=("Renovera köket",),
        task_titles=("Följ upp fakturor", "Beställ ny bänkskiva"),
        contact_names=("Carina Öberg", "Eva Sandberg"),
    ),
)
