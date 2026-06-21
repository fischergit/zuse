# Analyse: Befehlsarten und Nutzerintentionen für Zuse

Diese Analyse beschreibt typische Nutzerbefehle, Formulierungen und Routing-Regeln für Zuses Intent-Erkennung. Sie ist als Grundlage für Klassifikation, Tool-Auswahl, Sicherheitsprüfung und Rückfragen gedacht.

## 1. Grundprinzipien für Intent-Erkennung

Zuse sollte Eingaben nicht nur nach Schlüsselwörtern, sondern nach **Handlungsabsicht**, **Objekt**, **Umfang**, **Risiko** und **Kontextabhängigkeit** klassifizieren.

Wichtige Dimensionen:

- **Absicht:** Was will der Nutzer erreichen?
- **Zielobjekt:** Datei, Projekt, Webseite, Shell-Befehl, Modell, Session, Wissen, externe App, Todo-Liste.
- **Operation:** Lesen, zusammenfassen, ändern, ausführen, löschen, konfigurieren, abbrechen, erklären.
- **Risiko:** rein informativ, lokal verändernd, extern verändernd, destruktiv, sicherheitsrelevant.
- **Autonomiegrad:** nur Vorschlag, nachfragen, selbst ausführen, vollständig autonom.
- **Kontextbedarf:** eindeutig aus Eingabe ableitbar oder abhängig von aktuellem Verzeichnis, Chat-Verlauf, letzter Aktion, sichtbarer UI.

## 2. Intent-Kategorien

### 2.1 Informationsabfrage / Recherche

**Zweck:** Nutzer möchte Wissen, Status, Erklärung, Zusammenfassung oder Vergleich erhalten. Normalerweise keine Dateiänderung.

Typische Formulierungen:

- „Was ist Zuse?“
- „Erkläre mir diese Datei.“
- „Fasse das Projekt zusammen.“
- „Was macht `agent.py`?“
- „Welche Tests gibt es?“
- „Zeig mir die verfügbaren Tools.“
- „Wie funktioniert die Konfiguration?“
- „Welche Dateien wurden zuletzt geändert?“
- „Recherchiere, wie man Playwright installiert.“
- „Vergleiche Claude und Ollama für dieses Projekt.“

Synonyme / Signalwörter:

- erklären, beschreiben, zusammenfassen, analysieren, prüfen, untersuchen, vergleichen, finden, suchen, auflisten, zeigen, ausgeben, status, diagnose.

Routing-Hinweise:

- Primär: Dateilesen, Suche, Browser-Recherche, Diagnosebefehle.
- Keine Schreiboperation ohne expliziten Änderungswunsch.
- Bei „prüfe“ unterscheiden zwischen statischer Inspektion und Ausführung von Tests/Kommandos.

Ambiguitäten:

- „Check das Projekt“ kann nur Lesen, Testausführung oder Reparatur bedeuten.
- „Sieh dir die Fehler an“ kann Log-Analyse, Testlauf oder konkrete IDE/UI-Ansicht meinen.

Rückfrage, wenn:

- kein Zielobjekt genannt ist und es mehrere plausible Objekte gibt;
- externe Recherche nötig wäre, aber der Nutzer offenbar lokale Projektanalyse meint;
- „prüfen“ potenziell kosten- oder zeitintensive Befehle erfordert.

---

### 2.2 Aufgabensteuerung / Agentensteuerung

**Zweck:** Nutzer steuert Arbeitsweise, Priorität, Autonomie oder Ablauf von Zuse.

Typische Formulierungen:

- „Mach das bitte komplett.“
- „Arbeite autonom weiter.“
- „Plane zuerst.“
- „Erstelle eine Todo-Liste.“
- „Nutze einen Subagenten dafür.“
- „Mach nur Recherche, keine Änderungen.“
- „Führe die Tests danach aus.“
- „Arbeite Schritt für Schritt.“
- „Gib mir nur das Ergebnis.“
- „Nicht fragen, einfach machen.“

Synonyme / Signalwörter:

- plane, erledige, weiter, autonom, automatisch, Schritt für Schritt, nur lesen, nicht ändern, delegiere, überprüfe, verifiziere, priorisiere.

Routing-Hinweise:

- Steueranweisung in Session-Kontext speichern oder für aktuelle Aufgabe anwenden.
- Kann mit fachlichem Intent kombiniert sein: „Plane und implementiere X“ = Planung + Dateiänderung + Tests.
- Explizite Einschränkungen („keine Änderungen“, „nur Vorschläge“) haben Vorrang vor impliziten Aktionsverben.

Ambiguitäten:

- „Weiter“ hängt vollständig vom letzten aktiven Ziel ab.
- „Mach es besser“ braucht ein Referenzobjekt.
- „Automatisch“ kann Tool-Autonomie, Genehmigungen oder Hintergrundmodus bedeuten.

Rückfrage, wenn:

- kein aktives Ziel existiert;
- „weiter“ nach abgeschlossener Aufgabe eingegeben wird;
- die gewünschte Autonomie Sicherheitsrichtlinien oder destruktive Operationen berührt.

---

### 2.3 Datei- und Datenoperationen

**Zweck:** Nutzer möchte Dateien lesen, erstellen, ändern, verschieben, löschen oder Daten transformieren.

Typische Formulierungen:

- „Öffne `README.md`."
- „Erstelle eine Datei `docs/usage.md`."
- „Ändere die Konfiguration in `pyproject.toml`."
- „Benenne diese Datei um.“
- „Lösche temporäre Dateien.“
- „Finde alle TODOs.“
- „Ersetze überall `foo` durch `bar`."
- „Formatiere die JSON-Datei.“
- „Extrahiere die Tabelle aus dieser CSV.“
- „Fasse alle Markdown-Dateien zusammen.“

Synonyme / Signalwörter:

- öffnen, lesen, anzeigen, schreiben, erstellen, anlegen, ändern, editieren, patchen, ersetzen, löschen, entfernen, verschieben, kopieren, umbenennen, formatieren, konvertieren, extrahieren.

Routing-Hinweise:

- Lesen: Filesystem-Read/Search.
- Schreiben/Ändern: diffbasierte Dateiänderung, danach optional Lint/Test.
- Datenoperation: Python/Shell nur wenn sinnvoll; bei kleinen Transformationen direkt editieren.
- Immer Pfadauflösung prüfen; relative Pfade beziehen sich auf aktuelles Arbeitsverzeichnis.

Ambiguitäten:

- „Öffne“ kann Dateiinhalt anzeigen oder in externer App öffnen bedeuten.
- „Räum auf“ kann Formatierung, Löschen, Refactoring oder Sortierung meinen.
- „Lösche alte Dateien“ benötigt Kriterien für „alt“.
- „Diese Datei“ setzt UI-/Chat-Kontext voraus.

Rückfrage, wenn:

- Zielpfad fehlt oder mehrere Dateien passen;
- Lösch-/Überschreiboperationen nicht eindeutig begrenzt sind;
- Ersetzung global und potenziell weitreichend ist;
- „diese“/„hier“/„oben“ ohne eindeutigen Kontext verwendet wird.

---

### 2.4 Code-, Build- und Testoperationen

**Zweck:** Nutzer möchte Code verstehen, ändern, ausführen, Fehler beheben oder Qualität prüfen.

Typische Formulierungen:

- „Fix die fehlenden Tests.“
- „Implementiere Feature X.“
- „Refactore die CLI.“
- „Führe die Test-Suite aus.“
- „Warum schlägt dieser Test fehl?“
- „Mach den Linter grün.“
- „Schreib Tests für diese Funktion.“
- „Starte die App lokal.“
- „Debugge den Fehler aus dem Log.“
- „Optimiere die Performance.“

Synonyme / Signalwörter:

- fixen, beheben, implementieren, ergänzen, refactoren, testen, bauen, starten, debuggen, optimieren, linten, typisieren, deployen.

Routing-Hinweise:

- Bei Implementierung: Code-Suche -> Plan -> Edit -> Tests/Lint -> Bericht.
- Bei Testausführung: bevorzugt vorhandene Projektbefehle erkennen (`pyproject.toml`, README, Makefile).
- Bei „starte“ unterscheiden zwischen kurzlebigem Kommando und langlaufendem Server.
- Deploy/Release ist extern wirksam und braucht explizite Bestätigung.

Ambiguitäten:

- „Mach es grün“ kann Tests, CI, Linter oder Typprüfung meinen.
- „Fix alles“ ist zu breit.
- „Starte die App“ kann Terminal, GUI, WebGUI oder Dienst meinen.

Rückfrage, wenn:

- Feature-Anforderung nicht testbar oder unklar ist;
- mehrere Test-/Build-Systeme existieren;
- Befehl langlaufend, kostenpflichtig oder extern verändernd ist;
- „alles“ unverhältnismäßig breit ist.

---

### 2.5 Shell-, System- und Automationsbefehle

**Zweck:** Nutzer möchte Kommandos ausführen, Umgebung prüfen, macOS steuern oder Browser/App-Automation verwenden.

Typische Formulierungen:

- „Führe `pytest` aus.“
- „Installiere die Abhängigkeiten.“
- „Aktiviere die venv.“
- „Öffne Safari mit dieser URL.“
- „Mach einen Screenshot.“
- „Kopiere das Ergebnis in die Zwischenablage.“
- „Starte den lokalen Server.“
- „Klicke auf den Button.“
- „Lies die aktuelle Webseite.“
- „Prüfe meine Systeminformationen.“

Synonyme / Signalwörter:

- ausführen, starten, installieren, öffnen, klicken, tippen, kopieren, einfügen, Screenshot, Browser, Terminal, shell, system, app.

Routing-Hinweise:

- Shell-Befehle mit Nebenwirkungen nach Risiko klassifizieren.
- GUI-Aktionen benötigen sichtbaren Kontext; vorher Screenshot/Screen lesen.
- Langlaufende Prozesse im Hintergrund starten und überwachen.
- Installationen, Netzwerkzugriffe und App-Steuerung separat genehmigen, falls nicht im Auto-/Yolo-Modus.

Ambiguitäten:

- „Installiere das“: Paket, App, Abhängigkeiten oder Extension?
- „Öffne das“: Datei, URL, App oder Ordner?
- „Klick da“ ohne Bildschirmreferenz.

Rückfrage, wenn:

- ein Shell-Befehl destruktiv, privilegiert oder extern wirksam ist;
- Ziel-App/URL/Element unklar ist;
- Nutzer „das“ sagt und kein eindeutiger vorheriger Gegenstand existiert.

---

### 2.6 Konfiguration und Präferenzen

**Zweck:** Nutzer möchte Modell, Provider, Modus, Reasoning, Memory, MCP, UI oder Projekt-/User-Einstellungen ändern.

Typische Formulierungen:

- „Wechsle zu Claude.“
- „Nutze lokal Ollama.“
- „Setze das Modell auf `qwen2.5-coder`."
- „Aktiviere Auto-Modus.“
- „Schalte sichtbares Denken aus.“
- „Merke dir, dass ich kurze Antworten bevorzuge.“
- „Vergiss diese Erinnerung.“
- „Zeig meine Sessions.“
- „Lade die Session `demo`."
- „Verbinde den MCP-Server.“

Synonyme / Signalwörter:

- setze, wechsle, aktiviere, deaktiviere, konfiguriere, speichere, merke, vergiss, lade, verbinde, trenne, Provider, Modell, Session, Memory.

Routing-Hinweise:

- Direkte Slash-Commands bevorzugen, wenn vorhanden (`/model`, `/effort`, `/learning`, `/memory`, `/save`, `/load`).
- Dauerhafte Präferenzen nur speichern, wenn sie stabil und ausdrücklich gemeint sind.
- Secrets/API-Keys nie im Klartext loggen oder unnötig speichern.

Ambiguitäten:

- „Benutze GPT“: Provider, Modellfamilie oder konkretes Modell?
- „Speichere das“: Datei, Session, Erinnerung oder Zwischenablage?
- „Vergiss das“: letzte Nachricht, Memory-Eintrag oder aktuelle Aufgabe?

Rückfrage, wenn:

- Konfigurationsziel nicht eindeutig ist;
- dauerhafte Speicherung oder Löschung betroffen ist;
- mehrere Sessions/Modelle/Provider mit ähnlichem Namen existieren.

---

### 2.7 Hilfe, Onboarding und Diagnose

**Zweck:** Nutzer braucht Bedienhilfe, verfügbare Befehle oder Fehlerdiagnose der Zuse-Installation.

Typische Formulierungen:

- „Hilfe.“
- „Was kannst du?“
- „Welche Slash-Commands gibt es?“
- „Wie starte ich die WebGUI?“
- „Warum funktioniert Zuse nicht?“
- „Prüfe mein Setup.“
- „Führe den Selftest aus.“
- „Welche Tools sind verfügbar?“
- „Wie nutze ich WhatsApp/Telegram?“

Synonyme / Signalwörter:

- Hilfe, help, commands, Anleitung, Setup, installiere, funktioniert nicht, Diagnose, doctor, selftest, tools.

Routing-Hinweise:

- Bei Bedienhilfe kurze, kontextbezogene Antwort.
- Bei Diagnose: `/doctor`, `/selftest` oder Inspektion von Konfigurationsdateien.
- Bei Installationsproblemen: erst OS, Python, venv, Provider, Keys/Ollama prüfen.

Ambiguitäten:

- „Geht nicht“ enthält keine Fehlerbeschreibung.
- „Hilfe mit Tests“ kann Bedienhilfe oder konkrete Fehlerbehebung sein.

Rückfrage, wenn:

- kein Symptom, Ziel oder Fehlermeldung genannt ist;
- Diagnose externen Zugriff oder Installation erfordert.

---

### 2.8 Korrektur, Undo und Anpassung

**Zweck:** Nutzer möchte letzte Aktion rückgängig machen, Ergebnis ändern oder Antwort korrigieren lassen.

Typische Formulierungen:

- „Mach das rückgängig.“
- „Undo.“
- „Stell die Datei wieder her.“
- „Nein, ich meinte X.“
- „Korrigiere die letzte Änderung.“
- „Nimm stattdessen Y.“
- „Das war falsch.“
- „Ändere den Ton, kürzer bitte.“
- „Verwirf deine letzte Antwort.“

Synonyme / Signalwörter:

- rückgängig, undo, revert, restore, wiederherstellen, korrigieren, stattdessen, nein, falsch, anders, kürzer, ausführlicher.

Routing-Hinweise:

- Bei Dateiänderung: letzte bekannte Änderung/diff identifizieren; `/undo` nutzen, wenn verfügbar.
- Bei Antwortstil: keine Tool-Nutzung nötig, nur neu antworten.
- Bei fachlicher Korrektur: neue Nutzerangabe hat Vorrang vor früherem Kontext.

Ambiguitäten:

- „Mach das rückgängig“ kann Dateiänderung, Shell-Aktion, Erinnerung, Session-Zustand oder Antwort meinen.
- „Korrigiere das“ ohne Objekt.

Rückfrage, wenn:

- mehrere kürzliche Aktionen rückgängig gemacht werden könnten;
- Undo nicht sicher oder nicht vollständig möglich ist;
- externe/irreversible Aktionen betroffen sind.

---

### 2.9 Abbruch, Pause und Beenden

**Zweck:** Nutzer will laufende Arbeit stoppen, Prozess beenden, Session verlassen oder Ziel wechseln.

Typische Formulierungen:

- „Stopp.“
- „Abbrechen.“
- „Hör auf.“
- „Beende das.“
- „Nicht weiter machen.“
- „Cancel.“
- „Exit.“
- „Schließe die Session.“
- „Stoppe den Server.“
- „Vergiss die Aufgabe, mach jetzt X.“

Synonyme / Signalwörter:

- stopp, stop, abbrechen, cancel, beenden, exit, quit, halt, pause, nicht weiter, lass es.

Routing-Hinweise:

- Sofort keine weiteren irreversiblen Aktionen starten.
- Bei laufendem Hintergrundprozess prüfen, ob Prozess gemeint ist.
- `/exit` nur bei explizitem Session-Ende.
- Zielwechsel: alte Aufgabe als abgebrochen markieren, neue Aufgabe starten.

Ambiguitäten:

- „Beende das“ kann Task, Server, App, Shell-Prozess oder Session meinen.
- „Stopp“ während Tool-Ausführung kann nur nach Abschluss des aktuellen atomaren Tools wirksam werden.

Rückfrage, wenn:

- mehrere Prozesse/Tasks laufen und kein Ziel genannt ist;
- Beenden Datenverlust verursachen kann;
- unklar ist, ob nur pausieren oder endgültig abbrechen gemeint ist.

---

## 3. Häufige mehrdeutige Befehle und empfohlene Behandlung

| Befehl | Mögliche Intents | Standardannahme | Rückfrage nötig? |
|---|---|---|---|
| „Mach das.“ | letzte vorgeschlagene Aktion, Implementierung, Ausführung | letzten klaren Vorschlag ausführen | Ja, wenn mehrere Vorschläge existieren |
| „Weiter.“ | Aufgabe fortsetzen, nächste Datei, nächste Seite | aktives Ziel fortsetzen | Ja, wenn kein aktives Ziel |
| „Öffne das.“ | Datei anzeigen, App öffnen, URL öffnen | Kontextobjekt öffnen/anzeigen | Ja, wenn Objekt/App unklar |
| „Check das.“ | lesen, testen, diagnostizieren, validieren | zunächst inspizieren, dann berichten | Ja, vor teuren/ändernden Tests |
| „Räum auf.“ | formatieren, löschen, refactoren, sortieren | ungefährliche Vorschläge machen | Ja, vor Änderungen/Löschen |
| „Fix es.“ | Fehler beheben, Tests reparieren, Text korrigieren | Fehlerkontext suchen und Plan erstellen | Ja, wenn kein Fehlerkontext |
| „Speichere das.“ | Datei, Session, Memory, Clipboard | nach Zieltyp fragen | Ja |
| „Vergiss das.“ | Memory löschen, Aufgabe verwerfen, Kontext ignorieren | nach Ziel fragen | Ja, außer direkt nach Memory-Eintrag |
| „Starte es.“ | App, Server, Test, Script | anhand Projekt/letztem Objekt ableiten | Ja, bei mehreren Startoptionen |
| „Mach es sicher.“ | Security-Fix, Berechtigungen, Secrets, defensive Checks | Analyse starten | Ja, wenn Ziel/Bedrohung fehlt |
| „Installiere alles.“ | Dependencies, App, Tools, Browser | Projektabhängigkeiten erkennen | Ja, vor Installation |
| „Zeig mir den Status.“ | Git, Tests, Kosten, Agent-Zustand, System | Agent-/Aufgabenstatus und ggf. Git | Ja, wenn spezifischer Status erwartet wird |

## 4. Regeln für Rückfragen

Zuse sollte Rückfragen stellen, wenn mindestens eine der folgenden Bedingungen erfüllt ist:

1. **Fehlendes Objekt:** Der Befehl enthält deiktische Wörter wie „das“, „dies“, „hier“, „oben“, ohne eindeutigen Kontext.
2. **Mehrere plausible Ziele:** Es gibt mehrere Dateien, Sessions, Prozesse, Modelle, Provider oder UI-Elemente, die passen.
3. **Destruktives Risiko:** Löschen, Überschreiben, Zurücksetzen, `rm`, `git reset`, `drop`, Massenersetzung oder Datenverlust möglich.
4. **Externe Wirkung:** Deployments, Pushes, Nachrichtenversand, Käufe, API-Aufrufe mit realen Nebenwirkungen.
5. **Sicherheits-/Privatsphäre-Risiko:** Secrets, persönliche Daten, Systemberechtigungen, Keychain, Browserprofile, Kontakte.
6. **Kosten-/Zeitrisiko:** Lange Builds, große Downloads, kostenpflichtige APIs, umfangreiche Webrecherche.
7. **Irreversibilität:** Aktion kann nicht zuverlässig zurückgenommen werden.
8. **Unklare Erfolgskriterien:** Kein überprüfbarer Endzustand für Implementierungs- oder Fix-Aufgaben.
9. **Konflikt mit vorheriger Anweisung:** Nutzer sagt z. B. „keine Änderungen“ und später „fix es“ ohne Klärung.
10. **Unzureichende Berechtigung:** Aktion erfordert Moduswechsel, Auto-Approval, macOS-Rechte oder Credentials.

### 4.1 Form der Rückfrage

Rückfragen sollten knapp, entscheidungsorientiert und mit sinnvollen Optionen formuliert sein.

Beispiele:

- „Meinst du mit ‚das‘ die Datei `README.md`, die letzte Antwort oder die aktuelle Aufgabe?“
- „Soll ich nur analysieren oder die Fehler auch direkt beheben?“
- „Ich habe zwei mögliche Server-Startbefehle gefunden: `zuse-web` und `zuse-gui`. Welchen soll ich starten?“
- „Das würde Dateien löschen. Soll ich zuerst eine Liste der betroffenen Dateien anzeigen?“
- „Soll diese Präferenz dauerhaft gespeichert werden oder nur für diese Session gelten?“

### 4.2 Wenn keine Rückfrage gestellt werden sollte

Zuse sollte nicht nachfragen, wenn:

- die Absicht eindeutig und risikoarm ist;
- eine sichere Vorstufe möglich ist, z. B. erst lesen, suchen, planen oder eine Liste anzeigen;
- der Nutzer explizit eine bekannte Slash-Command-Aktion ausführt;
- die Antwort rein informativ ist;
- der aktuelle Kontext nur eine plausible Interpretation zulässt.

In solchen Fällen sollte Zuse handeln und im Bericht erklären, welche Annahme getroffen wurde.

## 5. Prioritätsregeln bei kombinierten Befehlen

Viele Nutzerbefehle kombinieren mehrere Intents. Empfohlene Reihenfolge:

1. **Abbruch/Stop** hat höchste Priorität.
2. **Sicherheits- und Einschränkungsanweisungen** („nicht ändern“, „nur lokal“, „nicht ausführen“) gelten vor Aktionsverben.
3. **Explizite Slash-Commands** schlagen natürliche Interpretation.
4. **Korrekturen des Nutzers** überschreiben frühere Annahmen.
5. **Destruktive Aktionen** benötigen Bestätigung, auch wenn sie Teil einer größeren Aufgabe sind.
6. **Informationsgewinn vor Änderung:** Wenn unklar, erst analysieren/planen.
7. **Verifikation nach Änderung:** Bei Code-/Konfigurationsänderungen Tests, Lint oder gezielte Checks anbieten bzw. ausführen, wenn angemessen.

## 6. Empfohlenes Intent-Schema für Routing

Ein erkanntes Kommando kann intern als strukturierte Absicht dargestellt werden:

```json
{
  "intent": "file_edit | info_query | code_fix | config_change | help | correction | abort | shell_action | automation",
  "operation": "read | write | run | delete | summarize | configure | undo | stop",
  "targets": ["README.md"],
  "constraints": ["no_external_network", "no_file_changes"],
  "risk": "low | medium | high | destructive | external",
  "needs_clarification": false,
  "clarification_reason": null,
  "suggested_route": "filesystem | shell | browser | mac | memory | session | agent_loop",
  "verification": "tests | lint | diff_review | status_check | none"
}
```

## 7. Beispiele für Klassifikation

| Nutzereingabe | Intent | Route | Risiko | Verhalten |
|---|---|---|---|---|
| „Fasse dieses Repo zusammen.“ | Informationsabfrage | Dateisuche + Lesen | niedrig | Projektstruktur lesen, zusammenfassen |
| „Fix die Tests und committe.“ | Code-Fix + externe VCS-Aktion | Shell + Dateiänderung + Git | hoch | Fix/Test ausführen; vor Commit ggf. bestätigen |
| „Nur analysieren, nichts ändern.“ | Aufgabensteuerung + Info | Lesen/Suche | niedrig | Keine Schreibtools nutzen |
| „Lösch alle Logs.“ | Dateioperation | Filesystem/Shell | destruktiv | Betroffene Dateien auflisten und Bestätigung holen |
| „Wechsle zu gpt-5.“ | Konfiguration | Model/Provider | mittel | Modell setzen, bei unbekanntem Provider klären |
| „Undo.“ | Korrektur | Session/File undo | mittel | letzte Änderung identifizieren; bei Mehrdeutigkeit fragen |
| „Stopp den Server.“ | Abbruch/System | Hintergrundprozess | mittel | laufende Server finden; bei mehreren fragen |
| „Was kostet diese Session?“ | Informationsabfrage | Kostenstatus | niedrig | `/cost` bzw. Cost-Tracker anzeigen |
| „Öffne die Webseite und klick Login.“ | Browser-Automation | Browser | mittel | URL fehlt -> Rückfrage, außer Kontext vorhanden |

## 8. Minimaler Routing-Entscheidungsbaum

1. Enthält die Eingabe Stop-/Abbruchsignal?
   - Ja: laufende Aktion/Prozess stoppen oder klären, was gestoppt werden soll.
2. Ist es ein Slash-Command oder entspricht es eindeutig einem Slash-Command?
   - Ja: Slash-Command-Handler.
3. Enthält sie Korrektur/Undo-Signal?
   - Ja: letzte relevante Aktion bestimmen; bei Mehrdeutigkeit fragen.
4. Verlangt sie nur Information/Erklärung?
   - Ja: Lesen/Suchen/Recherchieren, keine Änderung.
5. Verlangt sie Änderung an Dateien/Code/Konfiguration?
   - Ja: Ziel und Risiko prüfen, ggf. planen, ändern, verifizieren.
6. Verlangt sie Shell, Browser, macOS oder externe Aktion?
   - Ja: Risiko und Berechtigung prüfen, ggf. bestätigen.
7. Ist Ziel oder Erfolgskriterium unklar?
   - Ja: Rückfrage mit Optionen.
8. Sonst: sichere Vorstufe ausführen und Annahmen nennen.

## 9. Empfehlungen für Trainings-/Testdaten

Für Intent-Erkennung sollten Testfälle enthalten:

- deutsch, englisch und gemischte Eingaben („fix bitte die tests“);
- Kurzbefehle („weiter“, „undo“, „stopp“, „status“);
- deiktische Referenzen („das“, „diese Datei“, „oben“);
- kombinierte Einschränkungen („analysiere und schlag Änderungen vor, aber editiere nichts“);
- riskante Operationen („lösche“, „reset“, „deploy“, „push“);
- Synonyme und Umgangssprache („mach grün“, „räum auf“, „läuft nicht“);
- explizite Tool-/UI-Ziele („Browser“, „Terminal“, „Zwischenablage“, „Screenshot“);
- Konfigurationsbefehle mit Provider-/Modellnamen;
- fehlerhafte oder unvollständige Befehle, bei denen Rückfragen erwartet werden.
