"""100 GUI/pipeline scenarios, not 100 proteins or new docking calculations.

50 Qt contracts, 36 pipeline contracts and 14 real installed native review cases.
Separate raw-input chronological release gates remain required.
"""
import ast
import json
from pathlib import Path

import system_validation as system

ROOT = Path(__file__).resolve().parents[1]


def methods(module):
    tree=ast.parse((ROOT/'tests'/(module+'.py')).read_text())
    return [module+'.'+c.name+'.'+m.name for c in tree.body if isinstance(c,ast.ClassDef)
            for m in c.body if isinstance(m,ast.FunctionDef) and m.name.startswith('test_')]


def main():
    out=ROOT/'validation/local/gui-foundation-100-20261022.json'
    if out.exists():raise ValueError('Existing local suite must not be overwritten')
    source=ROOT/'validation/runs/systematic-expanded-20261022'
    previous=json.loads((source/'summary.json').read_text())
    profile=json.loads((source/'suite.json').read_text())['profile']
    chosen=[]
    for module in ['test_ligand_library_panel','test_workflow_panels','test_linked_pose_review',
                   'test_gui_protocol_import','test_control_gui_authority']:
        chosen += [(test,'gui') for test in methods(module)]
    desktop=[
        'test_show_starts_real_polling_and_completion_is_seen_without_manual_refresh',
        'test_unchanged_poll_updates_elapsed_without_rebuilding_views_or_writing_state',
        'test_poll_does_not_wait_on_native_ray_lock_or_redraw_during_export',
        'test_scientific_workflow_toggle_survives_refresh_and_tracks_close_and_focus',
        'test_rapid_stage_switching_does_not_reflow_or_stall_the_workspace',
        'test_results_review_explicitly_detaches_and_redocks_without_state_change',
        'test_draft_forms_restore_but_scientific_approvals_do_not',
        'test_table_selection_is_only_a_proposal_until_approval_button',
        'test_completed_preparation_cannot_be_restarted_from_setup_panel',
        'test_finalization_requires_approval_and_submits_locked_gui_settings',
        'test_completed_bundle_disables_duplicate_finalization_and_remains_openable',
        'test_screening_preview_is_required_before_locked_run',
        'test_pose_interaction_loading_clears_old_image_and_rejects_stale_completion',
        'test_scientific_host_failure_is_visible_and_reconnectable',
        'test_failed_pdb_lookup_is_visible_after_poll_without_changing_candidates',
        'test_main_evidence_panel_highlights_recorded_residue_without_detaching']
    available=methods('test_desktop_workspace')
    for name in desktop:
        chosen.append((next(t for t in available if t.endswith('.'+name)),'gui'))
    assert len(chosen)==50
    for module in ['test_screening_workflow','test_ligand_tables','test_ligand_input']:
        chosen += [(test,'scientific') for test in methods(module)]
    final=[
        'test_real_report_and_bundle_are_valid_final_artifacts',
        'test_generated_bundle_passes_the_real_screening_checker',
        'test_protein_identity_is_visible_in_real_pdf_and_survives_bundle_round_trip',
        'test_protocol_only_reports_use_selected_prediction_not_first_box',
        'test_real_ad4_protocol_report_states_the_actual_method_not_na_vina_fields',
        'test_real_vina_protocol_report_has_only_vina_controls_and_no_results']
    available=methods('test_protocol_finalization_integration')
    final += [t.rsplit('.',1)[1] for t in available if t.rsplit('.',1)[1] not in final][:5]
    for name in final:
        chosen.append((next(t for t in available if t.endswith('.'+name)),'scientific'))
    assert len(chosen)==86 and len({t for t,_ in chosen})==86
    cases=[]
    for index,(test,runtime) in enumerate(chosen,1):
        executable='{gui_python}' if runtime=='gui' else '{scientific_python}'
        cases.append({'id':'contract-%03d'%index,'layer':'regression','driver':'command',
                      'coverage_level':'Qt contract with fixtures' if runtime=='gui' else 'Pipeline contract with fixtures',
                      'scenario':test,'timeout_seconds':180,'visual_review_required':False,
                      'argv':[executable,'{project}/validation/contract_worker.py','--test',test,'--out','{out}/receipt.json'],
                      'checks':[{'kind':'json','path':'receipt.json','keys':['status'],'equals':'passed'},
                                {'kind':'json','path':'receipt.json','keys':['tests_run'],'equals':1},
                                {'kind':'json','path':'receipt.json','keys':['skipped'],'equals':0}]})
    for row in previous['cases']:
        if row['layer']!='workflow' or row['status']!='passed':continue
        system.verify_saved(row,source)
        result=source/row['directory']/'case-result.json'
        cases.append({'id':'native-'+row['id'],'layer':'workflow','driver':'command','engine':row['engine'],
                      'requires':['desktop'],'coverage_level':'Native installed GUI controls on retained real pipeline output',
                      'target':'2R8N','inputs':{'source-case':{'path':str(result),'sha256':system.sha(result)}},
                      'timeout_seconds':600,'visual_review_required':True,
                      'argv':['{gui_python}','{project}/validation/retained_gui_worker.py',
                              '--source-case','{source-case}','--runtime','{runtime}',
                              '--scientific-python','{scientific_python}','--cli','{cli}',
                              '--out','{out}/worker']+(['--ray'] if row['id']=='indinavir-gui-vina' else []),
                      'checks':[{'kind':'json','path':'worker/summary.json','keys':['status'],'equals':'passed'},
                                {'kind':'json','path':'worker/summary.json','keys':['scientific_jobs_launched'],'equals':0},
                                {'kind':'json','path':'worker/summary.json','keys':['source_evidence_unchanged'],'equals':True},
                                {'kind':'file','path':'worker/panel.png'}]})
    assert len(cases)==100
    suite={'schema':system.SCHEMA,'name':'100 GUI/pipeline foundation scenarios — not 100 molecular examples',
           'profile':profile,'cases':cases,
           'coverage_limits':['50 Qt and 36 pipeline contracts may use fixtures/mocks',
                              '14 installed native reviews reuse real completed pipeline evidence; no new docking',
                              'C1–C5 chronological raw-input gates remain separate; 100 passing scenarios alone is not full release acceptance']}
    # Set before loading Qt; fixture tests remain explicitly offscreen. Native
    # workers remove this setting locally before creating their real viewport.
    profile['environment']['QT_QPA_PLATFORM']='offscreen'
    system.write(out,suite)
    print(json.dumps({'suite':str(out),'Qt_contracts':50,'pipeline_contracts':36,'native_reviews':14},indent=2))


if __name__=='__main__':
    main()
