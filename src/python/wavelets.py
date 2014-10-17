import mne
from mne.time_frequency.tfr import cwt_morlet
import random
import segment as sg
import sys
import numpy as np
from itertools import chain

def epochs_from_segment(segment, window_size=5.0):
    """
    Creates an MNE Epochs object from a Segment object

    Args:
    segment: The segment object we want to convert
    window_size: The size of the window in seconds

    Returns:
    An mne.Epochs object, where each epoch corresponds to a **window_size**
    part of the segment.
    """

    assert isinstance(segment, sg.Segment)

    ch_names = segment.get_channels().tolist()
    ch_types = ['eeg' for _ in range(len(ch_names))]
    sample_rate = segment.get_sampling_frequency()

    info = mne.create_info(ch_names, sample_rate, ch_types)

    # Slice the data so we can reshape array
    # n_samples = segment.get_n_samples()
    # samples_per_epoch = int(n_samples/sample_rate/window_size)
    # n_epochs = n_samples/samples_per_epoch
    # Reshape data into (n_epochs, n_channels, n_times) format
    # Ensure that the reshape is done correctly, ie. we retain continuity of
    # samples
    # reshaped = sliced_data.reshape(n_epochs, size(ch_names), samples_per_epoch)
    # sliced_data = segment.get_data()[:, :(samples_per_epoch*n_epochs)]

    raw = mne.io.RawArray(segment.get_data(), info)

    random_id = int(random.randrange(sys.maxint))
    events = make_fixed_length_events(raw, random_id,
                                      window_duration=window_size)
    epochs = mne.Epochs(raw, events, event_id=random_id, tmin=0,
                        tmax=window_size)

    return epochs

def make_fixed_length_events(raw, event_id, window_duration=5.):
    """Make a set of events separated by a fixed duration
    Parameters
    ----------
    raw : instance of Raw
    A raw object to use the data from.
    id : int
    The id to use.
    window_duration: float
    The duration to separate events by.
    Returns
    -------
    new_events : numpy array
    The new events.
    """
    start = raw.time_as_index(0)
    start = start[0] + raw.first_samp
    stop = raw.last_samp + 1
    frequency = raw.info['sfreq']

    if not isinstance(event_id, int):
        raise ValueError('event_id must be an integer')
    total_duration = int(np.floor(raw.n_times / frequency))
    floored_samples_per_window = int(np.floor(frequency * window_duration))
    floored_windows_per_segment = int(np.floor(total_duration /
                                               window_duration))

    stop = floored_windows_per_segment * floored_samples_per_window

    event_samples = np.arange(
        start, stop, np.floor(frequency * window_duration)).astype(int)

    n_events = len(event_samples)
    events = np.c_[event_samples, np.zeros(n_events, dtype=int),
                   event_id * np.ones(n_events, dtype=int)]
    return events

def extract_features_for_segment(segment, feature_length_seconds=60, window_size=5):
    """
    Creates an SPLV feature dictionary from a Segment object
    Args:
        segment: A Segment object containing the EEG segment from which we want
        to extract the features
    """

    # Here we define how many windows we will have to concatenate
    # in order to create the features we want
    frames = feature_length_seconds / window_size
    total_windows = int(segment.get_duration() / window_size)
    n_channels = len(segment.get_channels())
    iters = int(segment.get_duration() / feature_length_seconds)

    # Extract the features for individual frequency bands and windows
    decomposition_dict = segment_wavelet_synchrony(segment)

    feature_dict = {}
    # Combine the individual frequency bands and windows into features
    for index, offset in enumerate(xrange(0, total_windows, frames)):
        feature_list = []
        for array_list in decomposition_dict.itervalues():
            for i in xrange(frames):
                try:
                    sync_array = array_list[i + offset]
                    index_upper_1 = np.triu_indices(n_channels, 1)
                    sync_values = sync_array[index_upper_1].tolist()
                    feature_list.append(sync_values)
                # Because of the way the files are we will usually end up with
                # fewer frames than the theoretical value in the final segment,
                # so we need to guard against IndexError
                except IndexError:
                    # sys.stderr.write(("Out of index at index:%d offset:%d"
                    #                  " i:%d\n") % (index, offset, i))
                    # break or pass?
                    pass
        # Flatten the list of lists
        feature_dict[index] = list(chain.from_iterable(feature_list))

    if len(feature_dict) != iters:
        sys.stderr.write("WARNING: Wrong number of features created, expected"
                         " %d, got %d instead." % (iters, len(feature_dict)))

    return feature_dict




def eeg_rhythms():
    """
    Returns a dict of the EEG rhythm bands as described in
    [1] Comparing SVM and Convolutional Networks for Epileptic Seizure
    Prediction from Intracranial EEG
    """
    return {"delta" : (1, 4), "theta": (4, 7), "alpha" : (7, 13),
            "low-beta" : (13, 15), "high-beta" : (14, 30),
            "low-gamma" : (30, 45), "high-gamma" : (65, 101)}

def segment_wavelet_synchrony(segment, bands=None):
    """
    Calculates the wavelet synchrony of a Segment object

    Args:
        segment: A Segment object containing the EEG segment of which we want
        create the wavelet transform of.
        bands: A dict containing {band : (start_freq, stop_freq)} String to
        Tuple2 pairs.

    Returns:
        A dict containing {band: List[av_sync_array]} String to List of
        (n_channels x n_channels) ndarrays.
        Each band corresponds to a List of ndarrays where each array
        corresponds to the channel-to-channel synchrony within an epoch/window.
    """
    if bands is None:
        bands = eeg_rhythms()

    epochs = epochs_from_segment(segment)

    decomposition_dict = {}

    for band_name, (start_freq, stop_freq) in bands.iteritems():
        decomposition_dict[band_name] = band_wavelet_synchrony(
            epochs, start_freq, stop_freq)

    return decomposition_dict


def band_wavelet_synchrony(epochs, start_freq, stop_freq):
    """
    Computes the phase-locking synchrony SPLV for a specific frequency band,
    by computing the synchrony over all freqs in the [start_freq, stop_freq)
    band and taking the average.

    Args:
        epochs: The Epochs object for which we compute the wavelet synchrony.
        start_freq: The start of the frequency band
        stop_freq: The end of the frequency band, excluded from the calculation

    Returns:
         A List of (n_channels x n_channels) lower-triangular ndarrays.
         Each item in the list corresponds to the phase synchrony between
         the channels for an epoch/window.
    """
    freqs = range(start_freq, stop_freq)
    tf_decompositions = []
    for epoch in epochs:
        # Calculate the Wavelet transform for all freqs in the range
        tfd = cwt_morlet(epoch, epochs.info['sfreq'],
                         freqs, use_fft=True, n_cycles=2)
        n_channels, n_frequencies, n_samples = tfd.shape

        # Calculate the phase synchrony for all frequencies in the range
        av_phase_sync = np.zeros((n_channels, n_channels),
                                 dtype=np.double)
        for frequency_idx in xrange(n_frequencies):
            freq_tfd = tfd[:, frequency_idx, :]
            freq_phase_diff = np.zeros((n_channels, n_channels),
                                       dtype=np.double)
            for i, ch_i in enumerate(range(0, n_channels)[:-1]):
                for ch_j in range(0, n_channels)[i+1:]:
                    # Get the wavelet coefficients for each channel
                    ch_i_vals = freq_tfd[ch_i, :]
                    ch_j_vals = freq_tfd[ch_j, :]
                    # Phase difference between two segments is derived
                    # from the angle of their wavelet coefficients
                    angles = ((ch_i_vals * ch_j_vals.conjugate()) /
                              (np.absolute(ch_i_vals) * np.absolute(ch_j_vals)))
                    phase_diff = np.absolute(angles.sum() / n_samples)

                    if (phase_diff > 1.0) or (phase_diff < 0.0):
                        sys.stderr.write(("WARNING: Invalid phase difference: "
                                          "%f\n") % phase_diff)
                    # Gather the values in an lower triangular matrix
                    freq_phase_diff[ch_i, ch_j] = phase_diff

            av_phase_sync += freq_phase_diff

        # The synchrony is averaged over the synchronies in all frequencies
        # in the band
        av_phase_sync /= n_frequencies

        tf_decompositions.append(av_phase_sync)

    return tf_decompositions

def band_wavelet_transform(epochs, start_freq, stop_freq):
    """
    Computes the wavelet transform for a specific frequency band,
    by computing the transform over all freqs in the [start_freq, stop_freq)
    band and taking the average.

    Args:
        epochs: The Epochs object for which we compute the wavelet transform.
        start_freq: The start of the frequency band
        stop_freq: The end of the frequency band, excluded from the calculation

    Returns:
        A List containing numpy arrays (n_channels, n_samples), each array
        corresponds to one epoch/window in the epochs segment.
    """
    from warnings import warn
    warn("Do not use! We average over synchronies and not wavelet coefficients!")
    freqs = range(start_freq, stop_freq)
    tf_decompositions = []
    for epoch in epochs:
        # Calculate the Wavelet transform for all freqs in the range
        tfd = cwt_morlet(epoch, epoch.info['sfreq'],
                         freqs, use_fft=True, n_cycles=2)
        n_channels, n_frequencies, n_samples = tfd.shape

        # Get the average over all the frequencies in the range
        av_tfd = np.empty((n_channels, n_samples), dtype=np.complex)
        for frequency_idx in xrange(n_frequencies):
            av_tfd += tfd[:, frequency_idx, :]
        av_tfd /= n_frequencies

        tf_decompositions.append(av_tfd)

    return tf_decompositions