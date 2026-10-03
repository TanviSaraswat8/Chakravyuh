"""Models used in the real-data experiments. All are trained from scratch on the named real splits.

- RulesClassifier / RulesMultiLabel: transparent keyword lexicons (stated below), no training.
- tfidf_lr / tfidf_svm: word 1-2-gram TF-IDF + logistic regression / linear SVM (SVM probabilities by
  sigmoid calibration on the validation split, used only for calibration metrics).
- tagger_arch: the current Chakravyuh tagger's exact text pipeline (char_wb 2-5 TF-IDF, 60k features,
  one-vs-rest logistic regression, C=4, balanced), retrained on the real labels.
- CharTransformer: a small character-level transformer trained from scratch on CPU. No pretrained
  weights (Hugging Face is unreachable here), so it is a capacity baseline, not a pretrained LM.
"""

from __future__ import annotations

import time

import numpy as np
from sklearn.calibration import CalibratedClassifierCV
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.frozen import FrozenEstimator
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score
from sklearn.multiclass import OneVsRestClassifier
from sklearn.pipeline import Pipeline
from sklearn.svm import LinearSVC

SEED = 13
TRANSFORMER_EPOCHS = 5


def word_tfidf() -> TfidfVectorizer:
    return TfidfVectorizer(analyzer="word", ngram_range=(1, 2), min_df=2, sublinear_tf=True, max_features=200_000,
                           lowercase=True, token_pattern=r"(?u)<\w+>|\b\w+\b")


def char_tfidf() -> TfidfVectorizer:          # identical to chakravyuh.ml.tagger.TacticTagger
    return TfidfVectorizer(analyzer="char_wb", ngram_range=(2, 5), min_df=2, sublinear_tf=True, max_features=60_000)


def fit_select(make, Cs, Xtr, ytr, Xva, yva, score):
    """Fit one model per C, keep the best on validation."""
    best, best_s, tried = None, -1.0, {}
    for C in Cs:
        m = make(C).fit(Xtr, ytr)
        s = score(yva, m.predict(Xva))
        tried[str(C)] = round(float(s), 4)
        if s > best_s:
            best, best_s = m, s
    return best, tried


def macro_f1(y, p):
    return f1_score(y, p, average="macro", zero_division=0)


def tfidf_lr(Xtr, ytr, Xva, yva, multilabel=False, vec=word_tfidf):
    def make(C):
        clf = LogisticRegression(C=C, max_iter=3000, class_weight="balanced", random_state=SEED)
        return Pipeline([("vec", vec()), ("clf", OneVsRestClassifier(clf) if multilabel else clf)])
    return fit_select(make, [0.5, 2.0, 8.0], Xtr, ytr, Xva, yva, macro_f1)


def tfidf_svm(Xtr, ytr, Xva, yva, multilabel=False):
    def make(C):
        clf = LinearSVC(C=C, class_weight="balanced", random_state=SEED)
        return Pipeline([("vec", word_tfidf()), ("clf", OneVsRestClassifier(clf) if multilabel else clf)])
    model, tried = fit_select(make, [0.1, 0.5, 2.0], Xtr, ytr, Xva, yva, macro_f1)
    cal = None
    if not multilabel:
        cal = CalibratedClassifierCV(FrozenEstimator(model), method="sigmoid").fit(Xva, yva)
    return model, tried, cal


def tagger_arch(Xtr, ytr, multilabel=False):
    clf = LogisticRegression(max_iter=2000, C=4.0, class_weight="balanced", random_state=SEED)
    return Pipeline([("vec", char_tfidf()), ("clf", OneVsRestClassifier(clf))]).fit(Xtr, ytr)


# ------------------------------------------------------------------------------------------ rules
class RulesClassifier:
    """Keyword-count classifier. `lexicon` maps class -> keywords (lower-case substrings);
    the class with most hits wins; no hit -> `default`."""

    def __init__(self, lexicon: dict[str, list[str]], default: str) -> None:
        self.lexicon, self.default = lexicon, default
        self.classes_ = sorted(set(lexicon) | {default})

    def scores(self, texts):
        return np.array([[sum(k in t.lower() for k in self.lexicon.get(c, [])) for c in self.classes_] for t in texts])

    def predict(self, texts):
        s = self.scores(texts)
        return np.array([self.classes_[i] if s[j, i] > 0 else self.default for j, i in enumerate(s.argmax(1))])

    def predict_proba(self, texts):
        s = self.scores(texts).astype(float) + 1e-3
        return s / s.sum(1, keepdims=True)


class RulesMultiLabel:
    def __init__(self, lexicon: dict[str, list[str]], labels: list[str]) -> None:
        self.lexicon, self.labels = lexicon, labels

    def predict(self, texts):
        return np.array([[int(any(k in t.lower() for k in self.lexicon.get(lab, []))) for lab in self.labels]
                         for t in texts])


SCAM_TYPE_LEXICON = {
    "banking": ["bank", "account", "kyc", "card", "otp", "debit", "credit", "sbi", "yono", "pan ", "netbanking",
                "banco", "cuenta", "tarjeta", "rekening", "compte", "konto", "carte", "paypal", "transaction"],
    "delivery": ["parcel", "package", "delivery", "deliver", "shipment", "courier", "customs", "usps", "dhl", "fedex",
                 "royal mail", "evri", "postnl", "paquete", "envío", "correos", "pakket", "bezorg", "colis",
                 "livraison", "paket", "sendung", "tracking"],
    "government": ["tax", "refund", "irs", "hmrc", "toll", "fine ", "police", "court", "government", "challan",
                   "dmv", "license", "multa", "hacienda", "dgt", "belasting", "boete", "amende", "impôt", "gov"],
    "telecom": ["recharge", "sim", "airtel", "vodafone", "jio", "bsnl", "mobile number", "data pack", "telecom",
                "verizon", "at&t", "t-mobile", "your plan", "bill"],
    "wrong number": ["wrong number", "is this", "are you", "long time no see", "how have you been"],
    "hey mum/dad": ["mum", "mom", "dad", "mama", "papa", "new number", "my phone broke", "lost my phone"],
    "spam": ["offer", "discount", "sale", "casino", "bonus", "free spins", "% off", "unsubscribe", "promo", "loan"],
}
LURE_LABELS = ["authority", "time/urgency", "distraction", "need and greed", "kindness", "herd", "dishonesty"]
LURE_LEXICON = {
    "authority": ["bank", "police", "government", "official", "court", "tax", "irs", "hmrc", "customs", "department",
                  "ministry", "sbi", "security", "service"],
    "time/urgency": ["urgent", "immediately", "today", "now", "within", "expire", "last chance", "suspend", "block",
                     "final", "asap", "24 h", "hours"],
    "distraction": ["click", "link", "verify", "update", "confirm", "follow", "tap"],
    "need and greed": ["win", "won", "prize", "reward", "cashback", "refund", "free", "bonus", "earn", "profit", "gift"],
    "kindness": ["help", "please", "mum", "mom", "dad", "friend", "donate", "favour", "favor"],
    "herd": ["members", "everyone", "thousands", "people", "join", "others"],
    "dishonesty": ["secret", "don't tell", "do not tell", "between us", "confidential"],
}
SCAM_LEGIT_PROMO_LEXICON = {
    "scam": ["verify", "suspend", "blocked", "kyc", "prize", "won", "urgent", "refund", "password", "otp", "click here",
             "update your", "penalty", "fine", "expire", "parcel", "unpaid", "claim"],
    "promo": ["offer", "discount", "sale", "recharge", "plan", "% off", "cashback", "free data", "download", "shop",
              "unsubscribe", "valid till", "t&c", "rs."],
}


# ------------------------------------------------------------------------------- char transformer
class CharTransformer:
    """Small char-level Transformer encoder (from scratch). multilabel=False -> softmax over classes."""

    def __init__(self, classes, multilabel=False, max_len=200, d=96, layers=2, heads=4, epochs=5, lr=2e-3,
                 batch=64, vocab_size=2500):
        self.classes, self.multilabel = list(classes), multilabel
        self.max_len, self.d, self.layers, self.heads = max_len, d, layers, heads
        self.epochs, self.lr, self.batch, self.vocab_size = epochs, lr, batch, vocab_size
        self.history: list[dict] = []

    def config(self) -> dict:
        return {k: getattr(self, k) for k in ("max_len", "d", "layers", "heads", "epochs", "lr", "batch", "vocab_size")}

    def _encode(self, texts):
        ids = np.zeros((len(texts), self.max_len), dtype=np.int64)
        for i, t in enumerate(texts):
            s = [self.vocab.get(ch, 1) for ch in t.lower()[: self.max_len]]
            ids[i, : len(s)] = s
        return ids

    def _net(self, n_out):
        import torch
        from torch import nn

        d, L = self.d, self.max_len

        class Net(nn.Module):
            def __init__(s):
                super().__init__()
                s.emb = nn.Embedding(len(self.vocab) + 2, d, padding_idx=0)
                s.pos = nn.Parameter(torch.zeros(1, L, d))
                layer = nn.TransformerEncoderLayer(d, self.heads, 2 * d, dropout=0.1, batch_first=True)
                s.enc = nn.TransformerEncoder(layer, self.layers, enable_nested_tensor=False)
                s.head = nn.Linear(d, n_out)

            def forward(s, x):
                pad = x == 0
                h = s.enc(s.emb(x) + s.pos[:, : x.shape[1]], src_key_padding_mask=pad)
                keep = (~pad).unsqueeze(-1).float()
                return s.head((h * keep).sum(1) / keep.sum(1).clamp(min=1))
        return Net()

    def fit(self, Xtr, ytr, Xva, yva, score):
        import torch
        torch.manual_seed(SEED)
        from collections import Counter
        counts = Counter(ch for t in Xtr for ch in t.lower()[: self.max_len])
        self.vocab = {ch: i + 2 for i, (ch, _) in enumerate(counts.most_common(self.vocab_size))}
        Xt = torch.tensor(self._encode(Xtr))
        if self.multilabel:
            Yt = torch.tensor(np.asarray(ytr), dtype=torch.float32)
            pos = Yt.mean(0).clamp(min=1e-3)
            loss_fn = torch.nn.BCEWithLogitsLoss(pos_weight=((1 - pos) / pos).clamp(max=20))
        else:
            idx = {c: i for i, c in enumerate(self.classes)}
            Yt = torch.tensor([idx[y] for y in ytr])
            freq = torch.bincount(Yt, minlength=len(self.classes)).float().clamp(min=1)
            loss_fn = torch.nn.CrossEntropyLoss(weight=(freq.sum() / (len(freq) * freq)))
        net = self._net(Yt.shape[1] if self.multilabel else len(self.classes))
        opt = torch.optim.AdamW(net.parameters(), lr=self.lr, weight_decay=0.01)
        best, best_state = -1.0, None
        g = torch.Generator().manual_seed(SEED)
        for ep in range(self.epochs):
            net.train()
            t0 = time.time()
            perm = torch.randperm(len(Xt), generator=g)
            for b in range(0, len(Xt), self.batch):
                j = perm[b: b + self.batch]
                opt.zero_grad()
                loss = loss_fn(net(Xt[j]), Yt[j])
                loss.backward()
                torch.nn.utils.clip_grad_norm_(net.parameters(), 1.0)
                opt.step()
            self.net = net
            s = score(yva, self.predict(Xva))
            self.history.append({"epoch": ep + 1, "val_macro_f1": round(float(s), 4), "seconds": round(time.time() - t0, 1)})
            print(f"    transformer epoch {ep + 1}: val macro-F1 {s:.4f} ({time.time() - t0:.0f}s)", flush=True)
            if s > best:
                best = s
                best_state = {k: v.clone() for k, v in net.state_dict().items()}
        net.load_state_dict(best_state)
        self.net = net
        return self

    def _logits(self, texts):
        import torch
        self.net.eval()
        out = []
        with torch.no_grad():
            X = torch.tensor(self._encode(texts))
            for b in range(0, len(X), 512):
                out.append(self.net(X[b: b + 512]))
        return torch.cat(out)

    def predict_proba(self, texts):
        import torch
        z = self._logits(texts)
        return (torch.sigmoid(z) if self.multilabel else torch.softmax(z, -1)).numpy()

    def predict(self, texts):
        p = self.predict_proba(texts)
        if self.multilabel:
            return (p >= 0.5).astype(int)
        return np.array(self.classes)[p.argmax(1)]

    def __getstate__(self):
        st = dict(self.__dict__)
        if "net" in st:
            st["net_state"] = {k: v.cpu() for k, v in st.pop("net").state_dict().items()}
        return st
