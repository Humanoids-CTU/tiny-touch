"""Coding-setup use cases that span two project databases."""


def inherit_coding_setup(source_repo, target_repo):
    setup = source_repo.load_coding_setup()
    if setup is None or source_repo.load_preparation_state() != "ready":
        raise ValueError("Review and prepare the source video's coding setup first")
    target_repo.save_coding_setup(setup, preparation_state="draft")
    return setup
