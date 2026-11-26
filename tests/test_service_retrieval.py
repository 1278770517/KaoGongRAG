import asyncio
import unittest

from rag_service.retrieval import retrieve


def test_public_response_hides_raw_answer_and_review_image_link():
    from rag_service.retrieval import public_parent

    parent = {
        "question_id": "q",
        "raw_text": "答案B",
        "images": [{"alt": "答案"}],
        "image_asset_ids": ["a"],
    }
    safe = public_parent(parent)
    assert "raw_text" not in safe and "images" not in safe
    assert public_parent(parent, True)["image_urls"] == ["/assets/a?review=true"]


class RetrievalTests(unittest.IsolatedAsyncioTestCase):
    async def test_timeout_degrades_and_cancellation_propagates(self):
        class Repo:
            async def hydrate(self, *args, **kwargs):
                return {}

        class Providers:
            async def dense(self, *args):
                await asyncio.sleep(60)

            async def sparse(self, *args):
                return []

        result = await retrieve("x", Repo(), Providers(), timeout=0.01)
        self.assertEqual(result["degraded"], ["dense"])
        task = asyncio.create_task(retrieve("x", Repo(), Providers()))
        await asyncio.sleep(0)
        task.cancel()
        with self.assertRaises(asyncio.CancelledError):
            await task

    async def test_version_filter_and_single_hydration(self):
        class Repo:
            calls = 0

            async def hydrate(self, ids, review=False):
                self.calls += 1
                return {
                    "q": {
                        "question_id": "q",
                        "question_version": 2,
                        "answer": "secret",
                        "analysis": "secret",
                        "image_asset_ids": [],
                    }
                }

        class Providers:
            async def dense(self, *a):
                return [{"question_id": "q", "question_version": 1}]

            async def sparse(self, *a):
                return [{"question_id": "q", "question_version": 2}]

        repo = Repo()
        result = await retrieve("test", repo, Providers())
        self.assertEqual(repo.calls, 1)
        self.assertEqual(len(result["results"]), 1)
        self.assertNotIn("answer", result["results"][0])

    async def test_degradation(self):
        class Repo:
            async def hydrate(self, *a, **kw):
                return {}

        class Providers:
            async def dense(self, *a):
                raise TimeoutError()

            async def sparse(self, *a):
                return []

        self.assertEqual(
            (await retrieve("x", Repo(), Providers()))["degraded"], ["dense"]
        )
