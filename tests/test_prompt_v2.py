from src.llm.client import LLMClient
from src.query.plan import TASKS,tasks_for,QueryPlan


def test_revised_prompt_has_task_and_review_in_user_message(monkeypatch):
    monkeypatch.setenv('MISTRAL_API_KEY','fixture')
    old=LLMClient({'model':'fixture'})
    new=LLMClient({'model':'fixture','prompt_template':'task-in-user-v2'})
    task=tasks_for({'semantic_prompt_version':'v2'})['defect']
    _,payload,_=new._request(task,'The motor is not working.')
    user=payload['messages'][1]['content']
    assert task.instruction in user and 'The motor is not working.' in user
    assert new.model_id!=old.model_id and task.prompt_version=='v2'
    assert TASKS['defect'].prompt_version=='v1'
    plan=QueryPlan.from_dict({'query_id':'q','semantic_tasks':['defect']},'version',tasks_for({'semantic_prompt_version':'v2'}))
    assert plan.semantic_tasks[0].prompt_version=='v2'
