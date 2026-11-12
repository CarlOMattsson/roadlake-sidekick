# Idag-widgeten och påminnelserna

[English](today-widget.md)

<!-- description: Idag-widgeten visar dagens uppgifter på Android-hemskärmen. Påminnelser kommer via ntfy och UnifiedPush, utan Googles tjänster. -->

Idag-widgeten visar dagens uppgifter på hemskärmen i Android. Påminnelserna säger till på morgonen och strax innan något ska göras. Båda hör till [Android-appen](android-app.sv.md).

:::note[Förhandsversion]
Widgeten och påminnelserna är inte provade på en riktig telefon. Leverans av push till riktiga telefoner är inte verifierad.
:::

## Lägg till widgeten

1. Para ihop appen med din server.
2. Håll inne på en tom yta på hemskärmen och välj widgetar.
3. Välj Sidekicks widget och dra ut den.

Widgeten är 4 × 2 rutor från början, och du kan ändra storleken. Innan appen är parad visar widgeten en knapp som öppnar appen där du kopplar den till servern.

## Bocka av en uppgift i widgeten

Du bockar av en uppgift direkt i widgeten. Du behöver inte öppna appen.

## Så ofta uppdateras widgeten

Widgeten hämtar dagens uppgifter ungefär var 30:e minut. En uppgift som du just har skapat i Claude kan därför dröja en stund innan den syns.

## Myntet i widgetens huvud

Utan licensnyckel visar widgeten ett litet mynt i sitt huvud. Det är påminnelsen om att det är gratisversionen. Ett tryck på myntet öppnar appen. En giltig nyckel tar bort myntet och ändrar inget annat.

## Det här påminner Sidekick om

- **Morgonsammanfattningen** kommer på morgonen, men bara om något ska göras idag eller är försenat.
- **Snart dags** kommer en stund innan en uppgift med klockslag ska göras.

Ingenting aviseras under de tysta timmarna på kvällen och natten. Tiderna ställs in på servern.

## Så kommer påminnelserna fram

Påminnelserna går via UnifiedPush, ett öppet sätt att väcka en app, och appen ntfy på telefonen. Sidekick använder inte Firebase och är inte beroende av Googles tjänster.

Det som skickas är en väckning utan innehåll. Telefonen vaknar, hämtar det som är aktuellt från din server och visar notisen själv. Vad som syns på låsskärmen följer telefonens egen inställning.

## Slå på påminnelser

1. Be den som sköter servern att slå på påminnelser. [Läs hur du ställer in påminnelser via ntfy](../operate/push-reminders.sv.md).
2. Installera appen ntfy på telefonen och öppna den en gång.
3. Tillåt aviseringar för Sidekick. Android 13 och senare frågar en gång, när telefonen har kopplats.
4. Öppna Inställningar i Sidekick och välj "Skicka testnotis".

På nyare Android-versioner behöver ntfy få använda batteriet utan begränsning. Annars kan väckningarna bli försenade.

## Om inget kommer fram

Inställningar i appen säger vad som saknas: ntfy-appen, tillstånd för aviseringar eller påminnelser på servern. [Gå till felsökningen i driftsguiden](../operate/pair-android.sv.md).
