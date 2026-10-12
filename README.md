# Pulse

**Un moniteur temps réel de votre machine, dans le terminal.**

*Version actuelle : **0.1.0** — première version fonctionnelle.*

Pulse est un tableau de bord console, dans la veine de `htop`, qui affiche en
direct l'état complet de votre PC : CPU, mémoire, swap, disque, réseau,
températures, ventilateurs, tensions, GPU, processus et services systemd.

Aucune dépendance externe obligatoire, aucun démon, aucune requête réseau.

---

## Sommaire

- [Aperçu](#aperçu)
- [Installation](#installation)
- [Lancement](#lancement)
- [Les vues](#les-vues)
- [Couleurs et alertes](#couleurs-et-alertes)
- [Raccourcis clavier](#raccourcis-clavier)
- [Options de la ligne de commande](#options-de-la-ligne-de-commande)
- [Ce que Pulse affiche](#ce-que-pulse-affiche)
- [Performance](#performance)
- [Architecture](#architecture)
- [Ajouter un capteur ou une vue](#ajouter-un-capteur-ou-une-vue)
- [Dépannage](#dépannage)
- [Feuille de route](#feuille-de-route)

---

## Aperçu

```
  • PULSE niko-1650-super  •  Linux Mint 22.3  •  up 3d 04h 57m                       19:50:28
 CPU   13%  •  RAM   18%                                                                 1.0s
  Overview  CPU  Memory  Disk  Network  Processes  Sensors  Services
╭─ CPU ────────────────────────────╮ ╭─ NETWORK ─────────────────────────╮ ╭─ SYSTEM ─────────────────╮
│TOTAL █████░░░░░░░░░░░░░░░░░ 13%   │ │TOTAL › 21.5 KiB/s      › 977 KiB/s│ │niko-1650-super • Linux Mint │
│                                   │ │                ▃▁▃█       █▁▂▅  │ │                             │
│freq 1.55 GHz  of 48%  load 0.00   │ │enp7s0             19 KiB/s 975KiB │ │up 3d 04h 57m  svc 45       │
│              gov schedutil        │ │▪ 1000Mb          192.168.1.32   │ │failed 1                    │
╰───────────────────────────────────╯ ╰──────────────────────────────────╯ ╰─────────────────────────────╯
```

Le tableau de bord **s'adapte à la taille de votre terminal** : 1, 2, 3 ou
4 colonnes selon la largeur disponible. Les panneaux sont priorisés, donc en
format étroit on garde l'essentiel (CPU, mémoire) plutôt que des panneaux
vides.

---

## Installation

### Prérequis

- **Linux** (testé sur Linux Mint 22.3 / Ubuntu 24.04)
- **Python 3.9+** (testé sur 3.12) — la bibliothèque standard `curses` suffit
- `psutil` — recommandé pour la vue Processus

### Option 1 — lancer depuis le dossier (aucune installation)

```bash
./bin/pulse
```

### Option 2 — installer avec pip

```bash
git clone <votre-repo> pulse
cd pulse
pip install -r requirements.txt
pip install -e .
pulse
```

### Option 3 — lien permanent sans installation

```bash
sudo ln -s "$(pwd)/bin/pulse" ~/.local/bin/pulse
```

### Dépendances

```bash
sudo apt install python3-psutil      #Ubuntu / Mint
```

`psutil` est **optionnel** : sans lui, tout fonctionne. Pulse lit `/proc`
directement pour les processus (plus rapide) et n'utilise `psutil` que comme
complément, jamais comme dépendance obligatoire.

---

## Lancement

```bash
./bin/pulse                       # tableau de bord, rafraîchissement 1 s
./bin/pulse -r 0.15               # temps réel (~7 images/s)
./bin/pulse --view Processes      # ouvrir directement sur une vue
./bin/pulse --ascii               # glyphes ASCII (terminaux sans Unicode)
```

---

## Les vues

| Vue | Touche | Contenu |
|---|---|---|
| **Overview** | `1` | Tableau de bord multi-panneaux : CPU, mémoire, GPU, températures, réseau, disque, systèmes de fichiers, sockets, services, top processus |
| **CPU** | `2` | Détail par cœur, répartition user/system/iowait/steal, fréquence, governor, topologie, historique |
| **Memory** | `3` | Répartition RAM, cache, buffers, slab, swap, pagination, commits, historique |
| **Disk** | `4` | Débits par périphérique, IOPS,.await, utilisation, points de montage, inodes |
| **Network** | `5` | Interfaces, débits, adresses IP, états TCP, ports en écoute |
| **Processes** | `6` | Tableau trié et filtrable : PID, utilisateur, CPU, mémoire, threads, E/S |
| **Sensors** | `7` | Températures, ventilateurs, tensions, puissances, bridage thermique |
| **Services** | `8` | Services systemd actifs, en échec, activés au démarrage, conteneurs |

---

## Couleurs et alertes

Pulse colore chaque valeur selon sa **gravité**, pas seulement selon sa valeur.
Quatre niveaux sont utilisés partout, de façon cohérente :

| Niveau | Couleur | Signification |
|---|---|---|
| `ok` | 🟢 vert | normal |
| `warn` | 🟡 jaune | à surveiller |
| `high` | 🟠 orange | saturation approaches |
| `critical` | 🔴 rouge (inversé) | problème avéré |

### Ce qui change de couleur

- **Barres de progression** : dégradé vert → jaune → orange → rouge selon
  l'utilisation, avec des **repères `│`** matérialisant les seuils
  d'avertissement et de critique directement sur la barre.
- **Bordures de panneaux** : un panneau passe au rouge quand sa grandeur
  dépasse le seuil critique (CPU saturé, swap plein, disque > 95 %, GPU trop
  chaude…).
- **En-tête** : la barre change de couleur et affiche une **pastille d'alerte**
  avec le pire problème en cours (`• 6 /mnt/data/sda1 98%`).
- **Tableau des processus** : les lignes très actives sont en gras, les
  processus « critiques » sont inversées, la colonne d'état `R` (en cours
  d'exécution) est en vert.
- **Lignes de la vue Processus** : les valeurs CPU / mémoire sont colorées
  selon leur niveau ; les processus les plus saturés sont inversés pour ressortir.

### Tendances

De petites flèches `▲ ▼ ▬` indiquent si une valeur monte, descend ou reste
stable (CPU, RAM, réseau, écriture disque). Elles sont calculées sur les
derniers échantillons de l'historique.

### Seuils

Centralisés dans `pulse/alerts.py` (`THRESHOLDS`). Exemples :

```python
"cpu":  (60, 80, 92)     # avertissement, élevé, critique
"mem":  (70, 85, 94)
"swap": (55, 78, 92)     # tolérant : Linux=swapage de façon proactive
"temp": (60, 72, 84)     # °C
"fs":   (75, 88, 95)     # % de remplissage
```

Modifiez ces valeurs pour les adapter à votre machine.

---

## Performance

Pulse est conçu pour rester fluide même avec un intervalle de rafraîchissement
très court. Coût mesuré sur cette machine (12 cœurs, 480 processus) :

| Étape | Avant | Après |
|---|---|---|
| Collecte des processus | 199 ms | ~24 ms |
| Invocation `systemctl` | 930 ms | ~11 ms (1 seul appel) |
| Coût par cycle complet | ~235 ms | ~24 ms |
| Temps de rendu d'une image | 4,7 ms | ~4 ms |

Leviers d'optimisation :

- **Lecture directe de `/proc`** pour les processus (2 lectures de fichiers au
  lieu de 5+) au lieu de `psutil` sur le chemin critique — gain ×5.
- **Un seul appel `systemctl list-units --all`** au lieu de trois.
- **Intervalles par capteur** : le CPU chaque tick, les services toutes les 8 s,
  les conteneurs toutes les 30 s.
- **Rendu par lots** : les barres écrivent des chaînes entières d'un coup au
  lieu d'un caractère par `addstr`.
- **Découplage** : la collecte tourne dans un thread dédié ; le rendu ne fait
  que lire le dernier instantané.

Avec ~24 ms par cycle, le rafraîchissement par défaut est passé à **0,5 s** et
reste fluide jusqu'à 0,1 s (24 % du budget CPU à cette cadence).

> Le rendu n'a **jamais** été le goulot : une image coûte ~4 ms, soit 0,4 % du
> budget à 1 Hz. C'est l'acquisition qui l'était, et c'est elle qui a été
> optimisée.

---

## Raccourcis clavier

| Touche | Action |
|---|---|
| `Tab` / `Shift-Tab` | Vue suivante / précédente |
| `1` – `8` | Accès direct à une vue |
| `c` | Retour au tableau de bord |
| `q` / `Échap` | Quitter |
| `/` | Filtrer les processus (nom, commande, utilisateur ou PID) |
| `Échap` *(en filtre)* | Effacer le filtre |
| `s` | Changer la colonne de tri |
| `↑` `↓` ou `k` `j` | Déplacer la sélection |
| `Page↑` / `Page↓` | Sauter de 10 lignes |
| `g` / `Début` / `Fin` | Première / dernière ligne |
| `p` | Suspendre / reprendre le rafraîchissement |
| `r` | Réinitialiser les historiques |
| `+` / `-` | Ajuster l'intervalle de rafraîchissement (0,2 s à 5 s) |
| `?` | Afficher l'aide |

---

## Options de la ligne de commande

```
-r, --refresh SEC   Intervalle de rafraîchissement (0,1 à 10 s, défaut : 0,5)
-v, --view NOM      Vue de départ : Overview, CPU, Memory, Disk, Network,
                    Processes, Sensors, Services
    --ascii         Utilise des glyphes ASCII au lieu des caractères Unicode
    --keys          Affiche la barre de raccourcis en bas de l'écran
    --version       Affiche la version
    --help          Affiche l'aide
```

---

## Ce que Pulse affiche

### CPU
Utilisation totale, **pourcentage par cœur**, répartition `user` / `system` /
`iowait` / `steal` / `irq` / `nice`, fréquence courante et plage, governor,
topologie physique (cœurs, sockets, threads), charge moyenne, processus
actifs et bloqués, changements de contexte et interruptions par seconde.

### Mémoire
RAM utilisée / disponible / libre, cache, buffers, slab, shared, swap, pagination
(entrées/sorties par seconde), faults majeurs, HugePages, `Committed_AS`,
historique.

### Disque
Par périphérique : débit lecture/écriture, IOPS, **await**, taux
d'utilisation, type (HDD/SSD), taille. Par montage : espace utilisé, disponible,
pourcentage, inodes.

### Réseau
Par interface : débit RX/TX, paquets par seconde, erreurs, état du lien,
vitesse négociée, adresses IP. Global : états TCP, sockets UDP, ports en
écoute avec noms de services connus.

### Thermique & capteurs
Températures par capteur, ventilateurs (RPM), tensions, puissances, état des
dispositifs de refroidissement (CPU frequency scaling).

### GPU
NVIDIA via `nvidia-smi` (utilisation, VRAM, température, puissance, ventilo,
horloges) ; Intel/AMD via sysfs DRM lorsque disponible.

### Processus
PID, utilisateur, nom, état, CPU %, mémoire (RSS et %), threads, débit lecture
/ écriture, ligne de commande complète. Tri et filtre en direct.

### Services
Services systemd en cours d'exécution, unités en échec, unités activées au
démarrage, nombre de conteneurs Docker/Podman.

---

## Architecture

```
pulse/
├── bin/pulse                 lanceur exécutable
├── pulse/
│   ├── app.py                boucle principale, chrome, raccourcis
│   ├── dashboard.py          panneaux de la vue Overview
│   ├── views.py              vues détaillées (CPU, RAM, disque, ...)
│   ├── alerts.py             seuils, niveaux de gravité, pastille d'alerte
│   ├── collectors/           acquisition des données
│   │   ├── base.py           infrastructure commune, deltas
│   │   ├── cpu.py            /proc/stat, cpufreq
│   │   ├── memory.py         /proc/meminfo, /proc/vmstat
│   │   ├── disk.py           /proc/diskstats, statvfs
│   │   ├── network.py        /proc/net/dev, /proc/net/tcp
│   │   ├── sensors.py        /sys/class/hwmon, thermal
│   │   ├── gpu.py            nvidia-smi, sysfs DRM
│   │   ├── processes.py      lecture directe /proc (rapide)
│   │   ├── services.py       systemctl (un seul appel)
│   │   └── system.py         identité, batterie, conteneurs
│   ├── layout.py             moteur de placement des panneaux
│   ├── history.py            historiques circulaires (sparklines, tendances)
│   ├── theme.py              palette et ramps de couleur
│   ├── widgets.py            barres, jauges, sparklines, tableaux
│   └── util.py               formatage des unités
├── tools/
│   ├── render.py             banc de test TUI sans écran (pty + émulateur)
│   └── bench.py              mesure du temps de rendu et de collecte
├── pyproject.toml            installation pip
├── README.md · ROADMAP.md · LICENSE
```

### Deux principes

**1. L'acquisition est découplée du rendu.** Un thread dédié (`Sampler`)
collecte les données en arrière-plan ; la boucle de rendu ne fait que lire le
dernier instantané. L'interface reste fluide même si `systemctl` met 200 ms à
répondre.

**2. Chaque capteur possède son intervalle.** Le CPU se rafraîchit toutes les
secondes, les services toutes les 8 secondes, les systèmes de fichiers toutes
les 10 secondes, les conteneurs toutes les 30 secondes. Le `Registry`
(`collectors/__init__.py`) gère cette cadence et sert la dernière valeur
connue aux collecteurs qui ne sont pas encore échus.

### Ajouter un capteur

```python
# pulse/collectors/myprobe.py
from .base import Collector

class MyProbeCollector(Collector):
    name = "myprobe"
    interval = 2.0

    def collect(self) -> dict:
        return {"value": 42}
```

Puis enregistrez-le dans `collectors/__init__.py` :

```python
from .myprobe import MyProbeCollector
# ...
self._register("myprobe", MyProbeCollector())
```

La clé `data["myprobe"]` est désormais disponible dans toutes les vues.

---

## Dépannage

**« Terminal too small »** — redimensionnez à au moins 60×18.

**Glyphes affichés en `????`** — votre terminal ne gère pas Unicode. Utilisez
`./bin/pulse --ascii`, ou lancez avec `LANG=fr_FR.UTF-8`.

**Moins d'informations sur les processus** — la vue Processus fonctionne sans
`psutil` ; installez-le (`pip install psutil`) pour une résolution plus fine
des noms d'utilisateur sur les systèmes multi-utilisateurs.

**Aucune température** — les capteurs `hwmon` ne sont pas exposés. Ce n'est pas
rare sur les machines virtuelles. Vérifiez avec `sensors` ou
`cat /sys/class/hwmon/hwmon*/temp*_input`.

**Le GPU n'apparaît pas** — Pulse cherche `nvidia-smi` (NVIDIA) ou les nœuds
DRM sysfs (Intel/AMD). Sans pilote chargé, rien ne sera détecté.

**« needs an interactive terminal »** — vous avez redirigé la sortie.
Pulse est un programme TUI, pas un outil de ligne de commande.

---

## Feuille de route

Voir [ROADMAP.md](ROADMAP.md) pour le détail des versions à venir.

---

## Licence

MIT — voir [LICENSE](LICENSE).