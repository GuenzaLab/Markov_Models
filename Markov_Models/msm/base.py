from . import classifier as _classifier
from . import cluster as _cluster
from . import score as _score
from .. import analysis
import warnings
import numpy as np
import multiprocessing as mp

# TODO: Add multiprocessing to parallelize bootstrapping
class BaseMicroMSM(object):

    def __init__(self, BaseModel):
        self._base = BaseModel
        self._is_force_db = BaseModel._is_force_db
        self._is_reversible = BaseModel._is_reversible
        self._is_sparse = BaseModel._is_sparse
        self.lag = BaseModel.lag

    def fit(self, N=None, centroids=None, lag=None, **kwargs):
        if N is None:
            if centroids is None:
                raise AttributeError('''
                Neither number of microstates nor pre-computed centroids supplied.
                ''')
            else:
                # If given centroid data, label data with classifier `method`
                method = kwargs.get('method', 'KNeighborsClassifier')
                self.centroids = centroids
                self._N = self._base.n_microstates = centroids.shape[0]
                if method.lower() == 'kneighborsclassifier':
                    self.labels = _classifier._KNeighborsClassifier(self, **kwargs)
                if method.lower() == 'gaussiannb':
                    self.labels = _classifier._GaussianNB(self, **kwargs)
        else:
            # If number of microstates given, fit model with `method`
            method = kwargs.get('method', 'KMeans')
            tol = kwargs.get('tol', 1e-5)
            max_iter = kwargs.get('max_iter', 500)
            fraction = kwargs.get('fraction', 0.5)
            shuffle = kwargs.get('shuffle', True)
            self._N = self._base.n_microstates = N
            if method.lower() == 'kmeans':
                self.centroids, self.labels = _cluster._KMeans(self, **kwargs)
            elif method.lower() == 'minibatchkmeans':
                self.centroids, self.labels = _cluster._MiniBatchKMeans(self, **kwargs)
            elif method.lower() == 'kmedoids':
                self.centroids, self.labels = _cluster._KMedoids(self, **kwargs)

        # If fit updates lag time, update microstate lag, else use base
        if lag is None:
            lag = self.lag
        else:
            self.lag = lag

        # Build count and transition matrices
        self._C = analysis.count_matrix(self.labels, lag=lag, sparse=self._is_sparse)
        if self._is_reversible is True:
            if self._is_force_db is True:
                self._T = analysis.transition_matrix.sym_T_estimator(self._C)
            else:
                self._T = analysis.transition_matrix.rev_T_estimator(self._C)
        else:
            self._T = analysis.transition_matrix.nonrev_T_matrix(self._C)


    def predict(self, data, method='KNeighborsClassifier', **kwargs):
        if not hasattr(self, 'centroids'):
            raise AttributeError('''
            No fit instance has been run! Fit data, before ''')
        if method.lower() == 'kneighborsclassifier':
            return _classifier._KNeighborsClassifier(self, data=data, **kwargs)
        if method.lower() == 'gaussiannb':
            return _classifier._GaussianNB(self, data=data, **kwargs)

    def _count_matrix(self, lag=1):
        return analysis.count_matrix(self.labels, lag=lag, sparse=self._is_sparse)

    def _transition_matrix(self, lag=None):
        if lag is not None:
            C = self._count_matrix(lag=lag)
        else:
            C = self._C
        if self._is_reversible is True:
            if self._is_force_db is True:
                return analysis.transition_matrix.sym_T_estimator(C)
            else:
                return analysis.transition_matrix.rev_T_estimator(C)
        else:
            return analysis.transition_matrix.nonrev_T_matrix(C)

    @property
    def count_matrix(self):
        try:
            return self._C
        except:
            raise AttributeError('''
            No instance found. Microstate model must be fit first.''')

    @property
    def transition_matrix(self):
        try:
            return self._T
        except:
            raise AttributeError('''
            No instance found. Microstate model must be fit first.''')

    @property
    def metastability(self):
        return np.diagonal(self._T).sum()

    @property
    def stationary_distribution(self):
        return analysis.spectral.stationary_distribution(self._T, sparse=self._is_sparse)

    def eigenvalues(self, k=None, ncv=None):
        return analysis.spectral.eigen_values(self._T, k=k, ncv=ncv, sparse=self._is_sparse, rev=self._is_reversible)

    def _eigenvectors(self, k=None, ncv=None, left=True, right=True):
        return analysis.spectral.eigen_vectors(self._T, k=k, ncv=ncv, left=left, right=right, sparse=self._is_sparse, rev=self._is_reversible)

    def left_eigenvector(self, k=None, ncv=None):
        return self._eigenvectors(k=k, ncv=ncv, left=True, right=False)

    def right_eigenvector(self, k=None, ncv=None):
        return self._eigenvectors(k=k, ncv=ncv, left=False, right=True)

    def mfpt(self, origin, target):
        return analysis.timescales.mfpt(self._T, origin, target, sparse=self._is_sparse)

    def score(self, X, y=None, **kwargs):
        if y is None:
            y = self.predict(X)
        return _score.Silhouette_Score(X, y, **kwargs)

    def timescales(self, lags=None, **kwargs):
        its = analysis.timescales.ImpliedTimescaleClass(self)
        return its.implied_timescales(lags=lags, **kwargs)

    def update(self, **kwargs):
        for key, val in kwargs.items():
            if key == 'lag':
                self.lag = val
                self._C = self._count_matrix(lag=val)
                self._T = self._transition_matrix(lag=val)

class BaseMacroMSM(object):
    '''Macro level description of trajectory data, coarse grained via PCCA+
    Parameters
    ----------
    memberships :
    metastable_sets :
    metastable_clusters :
    Notes
    -----
    '''

    def __init__(self, BaseModel):
        self._base = BaseModel
        self._is_force_db = BaseModel._is_force_db
        self._is_reversible = BaseModel._is_reversible
        self._is_sparse = False
        self._micro = self._base.microstates
        self.lag = self._micro.lag

    def fit(self, n_macrostates, lag=None, method='PCCA'):
        self._N = n_macrostates
        self._base.n_macrostates = n_macrostates

        if lag is None:
            lag = self.lag
        else:
            self.lag = lag

        if self._N > self._micro._N-1:
            raise AttributeError(
                "Number of macrostates cannot be greater than N-1 of number of microstates.")
        if self._N >= 4000:
            self._is_sparse = self._base._is_sparse
            if not self._is_sparse:
                warnings.warn('''
                    Sparse methods are highly recommended for
                    microstates >= 4000! self.update(sparse=True)
                ''')

        elif self._N < 4:
            if self._is_sparse:
                raise AttributeError('''
                Too few macrostates to use the sparse method! Update to sparse=False''')

        if method.lower() =='gmm':
            analysis.coarse_grain.GMM(self, n_macrostates)
        elif method.lower() =='hc':
            analysis.coarse_grain.HC(self, n_macrostates)
        elif method.lower() == 'hmm':
            analysis.coarse_grain.HMM(self, n_macrostates)
        elif method.lower() == 'hpca':
            analysis.coarse_grain.HPCA(self, n_macrostates)
        elif method.lower() == 'pcca':
            analysis.coarse_grain.PCCA(self, n_macrostates, lag=lag)
        else:
            raise AttributeError('Method '+str(method)+' is not implemented!')

        self._C = analysis.count_matrix(self.labels, lag=lag, sparse=self._is_sparse)
        if not method.lower() == 'pcca' or not method.lower() == 'hpca':
            if self._is_reversible is True:
                if self._is_force_db is True:
                    self._T = analysis.transition_matrix.sym_T_estimator(self._C)
                else:
                    self._T = analysis.transition_matrix.rev_T_estimator(self._C)
            else:
                self._T = analysis.transition_matrix.nonrev_T_matrix(self._C)

    # TODO: Rewrite all of this nonsense. This should predict the macrostates from a given subset of data
    def predict(self, data, method='KNeighborsClassifier', **kwargs):
        if not hasattr(self._micro, 'centroids'):
            raise AttributeError('''
            Microstate fitting must be performed prior to macrostate prediction.''')
        if method.lower() == 'kneighborsclassifier':
            return _classifier._KNeighborsClassifier(self, data=data, labels=self.metastable_labels, **kwargs)
        if method.lower() == 'gaussiannb':
            return _classifier._GaussianNB(self, data=data, labels=self.metastable_labels, **kwargs)

    def _count_matrix(self, lag=None):
        if lag is None:
            lag = self.lag
        return analysis.count_matrix(self.labels, lag=lag, sparse=self._is_sparse)

    def _transition_matrix(self, lag=None):
        if lag is not None:
            C = self._count_matrix(lag=lag)
        else:
            C = self._C
        if self._is_reversible is True:
            if self._is_force_db is True:
                return analysis.transition_matrix.sym_T_estimator(C)
            else:
                return analysis.transition_matrix.rev_T_estimator(C)
        else:
            return analysis.transition_matrix.nonrev_T_matrix(C)

    @property
    def count_matrix(self):
        try:
            return self._C
        except:
            raise AttributeError('''
            No instance found. Macrostate model must be fit first.''')

    @property
    def transition_matrix(self):
        try:
            return self._T
        except:
            raise AttributeError('''
            No instance found. Macrostate model must be fit first.''')

    @property
    def metastability(self):
        return np.diagonal(self._T).sum()

    @property
    def stationary_distribution(self):
        return analysis.spectral.stationary_distribution(self._T, sparse=self._is_sparse)

    def eigenvalues(self, k=None, ncv=None):
        return analysis.spectral.eigen_values(self._T, k=k, ncv=ncv, sparse=self._is_sparse, rev=self._is_reversible)

    def _eigenvectors(self, k=None, ncv=None, left=True, right=True):
        return analysis.spectral.eigen_vectors(self._T, k=k, ncv=ncv, left=left, right=right, sparse=self._is_sparse, rev=self._is_reversible)

    def left_eigenvector(self, k=None, ncv=None):
        return self._eigenvectors(k=k, ncv=ncv, left=True, right=False)

    def right_eigenvector(self, k=None, ncv=None, lag=None, precomputed=False):
        return self._eigenvectors(k=k, ncv=ncv, left=False, right=True)

    def mfpt(self, origin, target):
        return analysis.timescales.mfpt(self._T, origin, target, sparse=self._is_sparse)

    def score(self, **kwargs):
        return _score.Silhouette_Score(self._micro.centroids, self.metastable_labels, **kwargs)

    def timescales(self, lags=None, estimate_error=False, **kwargs):
        def timescales(self, lags=None, **kwargs):
            its = analysis.timescales.ImpliedTimescaleClass(self)
            return its.implied_timescales(lags=lags, **kwargs)

    #def update(self, **kwargs):
    #    for key, val in kwargs.items():
    #        if key == 'lag':
    #            self.lag = val
    #            self._C = self._count_matrix(lag=val)
    #            self._T = self._transition_matrix(lag=val)

    #            self._micro.lag = val
    #            self._micro._C = self._micro._count_matrix(lag=val)
    #            self._micro._T = self._micro._transition_matrix(lag=val)
    #        elif key == 'rev':
    #            self._base._is_reversible = self._is_reversible = val
    #        elif key == 'sparse':
    #            self._base._is_sparse = self._is_sparse = val
