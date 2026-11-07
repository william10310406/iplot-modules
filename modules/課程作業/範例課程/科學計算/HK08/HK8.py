REQUIRES = []                                   # 用了別的套件就加在這；自己跑一次會自動補（這份只用標準庫）
import coursework; coursework.ensure(REQUIRES, __file__)  # 缺的在這一行裝好，裝完才往下 import
import random
from collections import Counter, defaultdict

# ── 從這裡開始是作業 ──
NAME = "HK8 n-gram 語言模型：n-gram language model"
DOCS = [
    ("N-gram language model (ScienceDirect)",
     "https://www.sciencedirect.com/topics/computer-science/n-gram-language-model"),
    ("Text generation using n-gram model (Towards Data Science)",
     "https://towardsdatascience.com/text-generation-using-n-gram-model-8d12d9802aa0/"),
]
NOTE = """<title>
n-gram language model
</title>
<content>
</content>
"""
CASES = {
    "case-1": dict(seed="the quick", label="seed 'the quick'，往後最多生 10 個字"),
    "case-2": dict(seed="over the", label="seed 'over the'，往後最多生 10 個字"),
}


class NGramLanguageModel:
    def __init__(self, n=3):
        """
        Initializes the N-gram language model.
        :param n: The size of the n-gram (e.g., 2 for Bigram, 3 for Trigram).
        """
        self.n = n
        # Maps a context (tuple of n-1 words) to a Counter of next words
        self.model = defaultdict(Counter)

    def _preprocess(self, text):
        """Tokenizes text into lowercase words."""
        return text.lower().split()

    def train(self, corpus):
        """
        Trains the model by counting n-grams from the corpus text.
        """
        words = self._preprocess(corpus)

        # If the corpus is shorter than the n-gram size, we can't train properly
        if len(words) < self.n:
            return

        # Slide a window over the words to extract contexts and target words
        for i in range(len(words) - self.n + 1):
            ngram = words[i:i + self.n]
            context = tuple(ngram[:-1])
            target_word = ngram[-1]
            self.model[context][target_word] += 1

    def get_next_word_probabilities(self, context_words):
        """
        Returns the probability distribution of the next word given a context.
        """
        # Preprocess context to match the lower-case training standard
        context_words = [w.lower() for w in context_words]

        # Ensure context matches the expected length (n-1)
        context = tuple(context_words[-(self.n - 1):])

        if context not in self.model:
            return {}

        # Calculate MLE probabilities: count(context + word) / count(context)
        total_count = sum(self.model[context].values())
        return {word: count / total_count for word, count in self.model[context].items()}

    def generate_text(self, seed_text, max_words=20):
        """
        Generates text using the trained n-gram model.
        """
        words = self._preprocess(seed_text)

        for _ in range(max_words):
            # Take the trailing n-1 words as context
            context = tuple(words[-(self.n - 1):])

            # If the context is unseen, stop generation
            if context not in self.model:
                break

            # Sample the next word based on weights (frequencies)
            choices = list(self.model[context].keys())
            weights = list(self.model[context].values())
            next_word = random.choices(choices, weights=weights)[0]

            words.append(next_word)

        return " ".join(words)


def compute(case):
    """算。純計算、不畫圖、不開視窗；回 {"text": …}：原本印在終端機的機率、和 Tk 的 Entry（seed）／Text（生出來的句子）。"""
    p = CASES[case]
    # 1. Sample corpus data
    sample_corpus = ( "the quick brown fox jumps over the lazy dog. " "the quick brown cat jumps over the fence. " "the lazy dog sleeps all day long.")
    # 2. Instantiate and train a Trigram (N=3) model
    trigram_model = NGramLanguageModel(n=3)
    trigram_model.train(sample_corpus)
    # 3. Check next-word probability distribution
    lines = ["--- Next Word Probabilities for context 'the quick' ---"]
    probs = trigram_model.get_next_word_probabilities(["the", "quick"])
    for word, prob in probs.items():
        lines.append(f"'{word}': {prob:.2f}")
    # 4. Generate new text from a seed phrase
    lines.append("\n--- Generated Text ---")
    seed = p["seed"]
    generated = trigram_model.generate_text(seed, max_words=10)
    lines.append(f"Seed: '{seed}' -> Output: '{generated}'")
    return {"text": "\n".join(lines)}


draw = None   # 純文字作業：沒有圖（下面固定尾段的 HOMEWORK 要用到這個名字）
stats = None  # 沒有另外的數字

# ── 以下不用改 ──
HOMEWORK = dict(name=NAME, docs=DOCS, note=NOTE, cases=CASES, compute=compute, draw=draw, stats=stats, file=__file__)
if __name__ == "__main__":
    raise SystemExit(coursework.main(HOMEWORK))
