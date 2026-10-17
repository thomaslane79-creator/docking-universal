"""Plain-language guidance for existing protocol settings; no scientific authority."""
from html import escape


SETTINGS_HELP = {
    'output_directory': ('Final output folder',
        'Where the final report and reusable protocol bundle will be saved.',
        'Choose a folder for this study. The .duprotocol bundle packages the approved receptor, '
        'docking regions, settings and retained evidence for later screening. Finalizing reuses '
        'the completed preparation; it does not dock new ligands now. The report documents the '
        'recipe and its limitations, not a completed ligand screen.'),
    'engine': ('Docking program',
        'The program that will search for ligand positions during later screening.',
        'AutoDock Vina and QuickVina-W are different search implementations; neither choice '
        'guarantees a correct pose or measured affinity. The selected program must be installed. '
        'Changing it can change sampling, runtime and results, so record it consistently. '
        'In this pipeline Vina uses Meeko flexible-macrocycle preparation when supported; '
        'QuickVina-W uses a rigid-conformer ensemble for large rings. This does not make the '
        'receptor flexible. The optional experimental AutoDock-GPU uses AD4 scoring and a '
        'different genetic/local search, not GPU Vina. Its energies are not interchangeable '
        'with Vina, and it rejects unvalidated macrocycles/metals instead of substituting '
        'another engine. No experimental validation is implied by selecting a program.'),
    'ph': ('Ligand preparation pH',
        'The pH used to consider ligand protonation states before docking.',
        'A chemical state is a particular protonation or tautomer form: it can differ in charge '
        'or hydrogen placement, not just 3D shape. Use the relevant experimental pH when known. '
        'More states can increase later work. This setting affects later ligand preparation; '
        'it does not change the already-prepared receptor or simulate water, acidity, or a '
        'complete solution environment during docking.'),
    'conformers': ('Starting shapes per chemical state',
        'How many independently generated ligand shapes to retain for each chemical state.',
        'A conformer is a starting 3D shape, not a docking pose or a cluster. Different shapes '
        'can help explore ring arrangements and flexible ligands. More retained shapes mean '
        'more docking runs; they do not guarantee more useful results. This is a retention '
        'limit, not the total number attempted, and fewer may be produced. The current saved '
        'recipe uses ETKDG generation and MMFF94 minimization (UFF fallback): that minimization '
        'uses a vacuum energy model, not a solvent-aware model. Its internal ligand energy is '
        'not the estimated docking binding energy.'),
    'seeds': ('Independent repeat runs (seeds)',
        'How many docking searches to repeat from each prepared starting shape.',
        'Each repeat uses a different random-number seed, so it may find a different pose. '
        'More repeats cost more time and help assess search repeatability, not experimental '
        'correctness. Runs multiply across starting shapes, chemical states, compounds and '
        'approved sites. Repeats are not extra chemical states or extra conformers.'),
    'base_seed': ('Starting random seed',
        'The numeric starting point used to generate repeatable random searches.',
        'The protocol stores consecutive docking seeds beginning with this number; it also '
        'uses this number for ligand ensemble generation. A seed is an identifier, not a '
        'biological parameter or quality setting. Keep it when comparing settings. Repeatable '
        'results also require the same structures, parameters and compatible software; the '
        'number alone is not enough. A larger number does not mean a better search.'),
    'exhaustiveness': ('Search effort (exhaustiveness)',
        'How hard the docking program searches within each approved region for one run.',
        'Higher effort explores more extensively and usually takes longer. It is separate '
        'from the number of repeat runs and the number of output poses. Extra effort can '
        'help difficult searches, but cannot repair an inappropriate receptor, wrong chemistry '
        'or a poorly chosen region, and does not guarantee the experimental pose.'),
    'modes': ('Maximum saved poses per run',
        'The upper limit on ligand placements returned by each individual docking run.',
        'A pose is one proposed position and shape of the ligand in the receptor. The engine '
        'may return fewer than this limit; the energy window also limits saved poses. Increasing '
        'this limit retains more alternatives but is not the same as increasing search effort. '
        'These are individual poses, not clusters, compounds or starting conformers. Clustering '
        'groups similar poses later; its cutoff is set in the screening step.'),
    'energy_range': ('Saved-pose energy window (kcal/mol)',
        'How far above one run’s lowest estimated binding energy other saved poses may be.',
        'This window applies within each docking run, not across the compound library. '
        'For example, a best energy of −9 kcal/mol with a 2 kcal/mol window admits poses up to '
        '−7 kcal/mol, subject to the maximum-pose limit. A wider window can retain more '
        'alternatives, including higher-energy poses; a smaller window discards them. It is '
        'not an experimental affinity cutoff. Lower estimated binding energy does not '
        'necessarily mean a pose is closer to an experimental structure.'),
    'ad4_runs': ('AD4 genetic-search runs per repeat',
        'How many independent genetic/local searches contribute one winner each in a GPU repeat.',
        'Each retained starting shape and seed launches this many AD4 Lamarckian genetic '
        'searches with ADADELTA local search. Every run winner is retained; these are not '
        'Vina modes or distinct pose clusters. Similar winners are clustered later. More '
        'runs increase work and do not guarantee better poses.'),
    'ad4_heuristic_cap': ('AD4 heuristic evaluation cap',
        'The maximum budget used by AD4’s rotatable-bond search heuristic.',
        'The heuristic derives its search budget from ligand flexibility, bounded by this '
        'cap; convergence autostop can finish sooner. It is not Vina exhaustiveness, a '
        'wall-clock limit or a guaranteed exact evaluation count for every genetic run. '
        'The experimental profile fixes population 150, 42,000 maximum generations and '
        '300 ADADELTA local iterations. A higher cap may take longer.'),
    'approval': ('Approve exploratory use',
        'Acknowledge that this recipe has no experimental pose-recovery control.',
        'A bound-ligand control tests whether the pipeline can recover a ligand’s known '
        'experimental pose in this target. This exploratory route has not passed that test. '
        'Approving allows creation of this exploratory protocol; it does not validate the '
        'binding site, approve hits or establish affinity. Region approval is a separate '
        'earlier decision. Screening will require its own explicit authorization.'),
}

# Always-visible teaching copy, beside each control rather than hover-only help.
AD4_ENGINE_GUIDE_HTML = '''
<h3>Learning guide: AD4, Vina and the GPU</h3>
<p><b>Two separate choices:</b> the scoring function estimates how favorable a
proposed protein–ligand pose is; the search algorithm tries to find favorable
poses. A GPU is the hardware running that search. AutoDock-GPU is not simply
AutoDock Vina moved to a faster processor.</p>
<p><b>What AD4 estimates:</b> AutoDock4 combines terms for atom attraction and
repulsion, hydrogen bonds, charge interactions, approximate desolvation (the
cost of moving groups away from water), and a penalty for lost ligand rotational
freedom. These approximations do not simulate an explicit water environment and
do not guarantee a more accurate result than Vina. Ligand starting-shape
minimization in this application still uses the separate vacuum MMFF94 model.</p>
<p><b>Reading the energy:</b> both methods report estimated binding energies in
kcal/mol, with more negative values generally favored by that method. However,
AD4 and Vina use different formulas: −9 from AD4 is not evidence of stronger
binding than −8 from Vina. Do not pool their energies into one hit ranking or
convert their difference into an affinity improvement. Even within one method,
the lowest-energy pose need not be the pose closest to an experimental structure.</p>
<p><b>How this search works:</b> a genetic search maintains a population of proposed
placements, combines and changes them, and refines them with local optimization
(ADADELTA). One GPU repeat launches the selected number of genetic runs; one
winner from every run is retained, including similar winners. The application
then uses the same pose clustering, PLIP interaction analysis, 2D/3D review and
report layout as the other engines. There is no Vina saved-pose window here.</p>
<p><b>Work and repeatability:</b> shapes × chemical states × seeds × sites × compounds
multiply the number of GPU repeats. Genetic-run count and the flexibility-based
evaluation cap control different parts of AD4 work; they cannot be translated
into Vina exhaustiveness. Autostop may end a search early. Speed depends on the
ligand, hardware and settings. A matching seed is repeatable only within the
tested build/device/method scope, not across engines or all computers.</p>
<p><b>Grid and supported scope:</b> AutoGrid creates atom-type energy maps before
searching. The 0.375 Å map cells can expand a requested box slightly to fit whole
even intervals; both requested and actual extents are saved in the protocol.
This first option uses a dry, rigid receptor and rejects unvalidated macrocycles,
metals and special atom types rather than changing their chemistry or falling
back to Vina. Production control calibration is not yet enabled for this engine:
an exploratory protocol does not become validated by choosing AD4.</p>
<p><b>Platforms and experimental status:</b> the common workflow is intended for
macOS, Windows and Linux. Only the pinned, locally tested Apple-Silicon OpenCL
128-work-item build is accepted in this release. Windows/Linux GPU builds need
their own hardware and driver acceptance checks. A work item is a GPU execution
lane, not a compound or a user CPU-thread setting. The defective one-work-item
configuration is blocked. Numerical and recovery controls on a small test panel
are not a general accuracy or speed guarantee.</p>
<p>Learn more (optional internet links):
<a href="https://pmc.ncbi.nlm.nih.gov/articles/PMC8063785/">AutoDock-GPU methods paper</a>;
<a href="https://autodock-vina.readthedocs.io/en/latest/docking_flexible.html">Official AD4/Vina energy-comparison warning</a>;
<a href="https://github.com/ccsb-scripps/AutoDock-GPU#supported-arguments">Upstream search settings</a>.
This explanation is available offline; opening links is optional.</p>
'''


INLINE_HELP = {
    'output_directory': 'The report documents the recipe; the .duprotocol file lets you reuse it for later screening.',
    'engine': 'Changing programs may change results. No program proves that a ligand binds.',
    'ph': 'A chemical state can differ in charge or hydrogen placement. This does not re-prepare the receptor or simulate solvent.',
    'conformers': 'More shapes mean more runs. Shapes are not docking poses. Current minimization uses MMFF94 vacuum energies, not solvent-aware energies.',
    'seeds': 'Different random starts test search repeatability, not experimental correctness. More repeats take longer.',
    'base_seed': 'Keep it when comparing settings. A bigger number is not better; the same inputs and software also matter.',
    'exhaustiveness': 'Higher effort usually takes longer. It is separate from repeat count and cannot correct a wrong receptor or site.',
    'modes': 'The engine may return fewer. Poses are individual placements, not clusters or compounds; similar poses are grouped later.',
    'energy_range': 'A wider window retains more alternatives. For a best energy of −9 and a window of 2, the cutoff is −7 kcal/mol.',
    'ad4_runs': 'One winner per genetic run is kept. All winners are clustered later; no Vina output window is applied.',
    'ad4_heuristic_cap': 'Autostop may finish sooner. Search effort and AD4 energies cannot be directly equated with Vina.',
    'approval': 'This recipe has not passed a test of recovering a known experimental ligand pose. Saving it does not validate hits or affinity.',
}


def settings_guide_html(values):
    parts = ['<h2>Finalize protocol: what each option means</h2>',
             '<p>A protocol is a reusable recipe for later docking. Finalizing packages your '
             'approved receptor and regions with these settings; it does not screen ligands now. '
             'Defaults are starting values, not settings proven for this receptor.</p>',
             '<p><b>Shape → repeated search → poses:</b> a chemical state can have several starting '
             'shapes; each shape gets repeated docking searches; each search can return several poses. '
             'Similar poses are grouped into clusters later.</p>']
    for key, (title, short, detail) in SETTINGS_HELP.items():
        is_ad4=values.get('engine_key')=='adgpu'
        if (key.startswith('ad4_') and not is_ad4) or (is_ad4 and key in ('exhaustiveness','modes','energy_range')):
            continue
        parts.append(f'<h3 id="{key}">{escape(title)}</h3><p><b>Current setting: '
                     f'{escape(str(values.get(key, "")))}</b></p><p>{escape(short)}</p><p>{escape(detail)}</p>')
        if key == 'engine':
            parts.append(AD4_ENGINE_GUIDE_HTML)
    parts.extend([
        '<h3>Other settings recorded in the current recipe</h3><p>These are not extra controls '
        'on this panel: MMFF94 vacuum ligand minimization, 0.75 Å conformer-generation pruning, '
        'tautomer enumeration and Gasteiger charges. Conformer pruning is different from the '
        'later docking-pose clustering cutoff. The receptor remains rigid.</p>',
        '<h3>After finalization</h3><p>Generate final report and .duprotocol saves the recipe. '
        'Open final report reads its documentation; Open bundle location shows the saved portable '
        'protocol. Choose ligands and review the workload in the next screening step. '
        'Existing saved protocols keep their recorded settings; reading this guide changes nothing.</p>',
        '<p>Parameter references: <a href="https://autodock-vina.readthedocs.io/en/stable/faq.html">'
        'AutoDock Vina FAQ</a> and <a href="https://autodock-vina.readthedocs.io/en/stable/vina.html">'
        'Vina output/search parameter documentation</a>. Guidance is bundled locally; no internet '
        'connection is needed to read it. Opening a reference link is optional.</p>'])
    return ''.join(parts)
